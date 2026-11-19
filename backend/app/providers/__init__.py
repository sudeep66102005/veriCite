"""OpenAI claim extraction and evidence assessment."""
from __future__ import annotations

import asyncio
import json

import httpx

from app.config import OPENAI_API_KEY, OPENAI_MODEL, PROVIDER_TIMEOUT

class ExtractionProviderError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


async def _request_json(prompt: str) -> dict:
    if not OPENAI_API_KEY.strip():
        raise ExtractionProviderError("OpenAI API key is missing.")
    try:
        async with asyncio.timeout(PROVIDER_TIMEOUT), httpx.AsyncClient(timeout=PROVIDER_TIMEOUT) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                json={
                    "model": OPENAI_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_object"},
                    "store": False,
                },
            )
            response.raise_for_status()
            choice = response.json()["choices"][0]
            if choice["finish_reason"] != "stop" or choice["message"].get("refusal"):
                raise ExtractionProviderError("OpenAI did not complete the requested assessment.")
            result = json.loads(choice["message"]["content"])
            if not isinstance(result, dict):
                raise ValueError("Expected JSON object")
            return result
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        raise ExtractionProviderError(
            f"OpenAI API request failed (HTTP {code}).",
            retryable=code in (408, 500, 502, 503, 504),
        ) from exc
    except (TimeoutError, httpx.TransportError) as exc:
        raise ExtractionProviderError("OpenAI request timed out or could not connect.", retryable=True) from exc
    except (ValueError, TypeError, IndexError, KeyError) as exc:
        raise ExtractionProviderError("OpenAI returned an invalid JSON response.") from exc


async def extract_claims_openai(
    paragraph_text: str,
    marked_span: str,
    allowed_ref_ids: list[str],
    original_span: str,
) -> list[dict]:
    """Call OpenAI to extract atomic claims from *paragraph_text*.

    Returns a list of dicts, each with keys:
        claim_text, original_span, ref_ids, qualifiers

    Any item whose ref_ids contain values not in *allowed_ref_ids* is filtered
    out.  Returns [] when no claims are found. Raises ExtractionProviderError if the request fails.
    """
    allowed_set = set(allowed_ref_ids)

    prompt = (
        "You are a scientific claim extractor. Given a paragraph from a manuscript "
        "and a marked citation span, extract all ATOMIC claims being made that are "
        "linked to the citations. Each atomic claim must be a single verifiable "
        "assertion with its qualifiers, units, comparators, population, and time point "
        "preserved. Do not merge multiple assertions into one claim.\n\n"
        "Return a JSON object with a claims array. Each array element: "
        '{"claim_text": str, "original_span": str, "ref_ids": [str], "qualifiers": str}\n'
        "- claim_text: normalized atomic assertion\n"
        "- original_span: exact substring of the paragraph that contains this claim\n"
        "- ref_ids: subset of the allowed_ref_ids that this claim specifically applies "
        "to (may be all of them if ambiguous)\n"
        "- qualifiers: any important qualifiers (population, time, units, negation)\n\n"
        "If no verifiable claims are found, return a JSON object with an empty claims array.\n"
        f"Important: ref_ids must only contain values from: {allowed_ref_ids}\n\n"
        f"Paragraph:\n{paragraph_text}\n\n"
        f"Marked citation span: {marked_span}\n"
        f"Representative clause: {original_span}"
    )

    items = (await _request_json(prompt)).get("claims")
    if not isinstance(items, list):
        raise ExtractionProviderError("OpenAI returned an invalid claims list.")

    validated = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = item.get("claim_text")
        if not isinstance(text, str) or not text.strip():
            continue
        original = item.get("original_span")
        ref_ids = item.get("ref_ids")
        matched = [
            ref_id for ref_id in ref_ids if isinstance(ref_id, str) and ref_id in allowed_set
        ] if isinstance(ref_ids, list) else []
        validated.append({
            "claim_text": text,
            "original_span": original if isinstance(original, str) and original else original_span,
            "ref_ids": matched,
        })

    return validated


# ---------------------------------------------------------------------------
# Stage 5 – Evidence classification
# ---------------------------------------------------------------------------


async def classify_claim_openai(
    claim_text: str,
    passages: list[dict],
    coverage: str,
    source_title: str,
) -> dict:
    """Call OpenAI to classify evidence for *claim_text* against *passages*.

    Each passage dict: {"passage_id": str, "text": str, "section": str|None,
                        "page": int|None}

    Returns a dict with keys: verdict, evidence_passage_ids, explanation,
    issue_flags.  On any error, returns a safe fallback dict.
    """
    valid_passage_ids = {p["passage_id"] for p in passages}

    # Build numbered passage block
    passage_lines: list[str] = []
    for idx, p in enumerate(passages, 1):
        section_info = f" [{p.get('section', '')}]" if p.get("section") else ""
        page_info = f" (p.{p['page']})" if p.get("page") is not None else ""
        passage_lines.append(
            f"[{idx}] passage_id={p['passage_id']}{section_info}{page_info}\n{p['text']}"
        )
    passages_block = "\n\n".join(passage_lines)

    prompt = (
        "You are a scientific evidence classifier. Given an atomic claim from a "
        "manuscript and numbered passages from the cited source paper, determine "
        "whether the source supports the claim.\n\n"
        "Verdict definitions:\n"
        "- SUPPORTED: source reports the same finding with material qualifiers intact\n"
        "- PARTLY_SUPPORTED: source establishes a narrower version (e.g. one subgroup "
        "when manuscript generalizes to all)\n"
        "- CONTRADICTORY: source gives positive contrary evidence for the same assertion, "
        "metric, population, and period\n"
        "- UNSUPPORTED: source was adequately inspected and does not substantiate the "
        "attribution\n"
        "- null verdict with status=unable_to_assess: source is unresolved, evidence "
        "unavailable, or retrieval inconclusive\n\n"
        f"Coverage: {coverage}\n"
        f"Source: {source_title}\n\n"
        "Rules:\n"
        "- Compare like quantities: check metric, unit, denominator, population, "
        "comparator, time window\n"
        "- If the manuscript gives a definite number and the source gives a different "
        "comparable number, the numerical assertion is CONTRADICTORY\n"
        "- A source that only discusses the same topic (without the specific finding) "
        "does NOT support the claim\n"
        "- Abstract-only evidence can support a claim explicitly stated in the abstract; "
        "abstain if claim depends on unavailable data\n\n"
        'Return JSON: {"verdict": "SUPPORTED"|"PARTLY_SUPPORTED"|"CONTRADICTORY"'
        '|"UNSUPPORTED"|null, "evidence_passage_ids": [str], "explanation": str, '
        '"issue_flags": [str]}\n'
        "- evidence_passage_ids: list of passage_ids you used (must be from the "
        "provided list)\n"
        "- explanation: 2-3 sentence reasoning\n"
        '- issue_flags: list of strings like "population_mismatch", '
        '"numerical_discrepancy", "unit_mismatch", "negation_present", '
        '"abstract_only_evidence"\n\n'
        f"Claim: {claim_text}\n\n"
        f"Passages:\n{passages_block}"
    )

    try:
        result = await _request_json(prompt)
    except ExtractionProviderError as exc:
        return {
            "verdict": None,
            "evidence_passage_ids": [],
            "explanation": str(exc),
            "issue_flags": ["provider_error"],
        }

    # Validate passage_ids — only keep ones actually in provided list
    raw_ids = result.get("evidence_passage_ids", [])
    result["evidence_passage_ids"] = (
        [pid for pid in raw_ids if isinstance(pid, str) and pid in valid_passage_ids]
        if isinstance(raw_ids, list)
        else []
    )

    # Ensure required keys exist with sane defaults
    result.setdefault("verdict", None)
    result.setdefault("explanation", "")
    result.setdefault("issue_flags", [])

    return result


__all__ = [
    "extract_claims_openai",
    "classify_claim_openai",
]
