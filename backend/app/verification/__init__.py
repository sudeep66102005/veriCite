"""Assess a claim against passages retrieved from its cited source."""
from uuid import uuid4

from app.models import (
    Assessment, AssessmentStatus, Claim, CoverageStatus, IdentityStatus, Passage,
    ResolvedSource, SemanticVerdict,
)
from app.providers import classify_claim_gemini


async def assess_claim_reference_pair(
    claim: Claim, source: ResolvedSource, passages: list[Passage], is_retracted: bool
) -> Assessment:
    assessment = Assessment(
        assessment_id=f"assessment_{uuid4().hex}",
        claim_id=claim.claim_id,
        ref_id=source.ref_id,
        assessment_status=AssessmentStatus.unable_to_assess,
        explanation="",
        issue_flags=["retracted_source"] if is_retracted else [],
    )
    if source.identity_status != IdentityStatus.matched:
        assessment.explanation = "The cited source could not be matched with enough certainty."
        assessment.issue_flags.append(source.identity_status.value)
        return assessment

    evidence = {
        p.passage_id: {"passage_id": p.passage_id, "text": p.verbatim_text,
                       "section": p.section, "page": p.page}
        for p in passages if p.source_id == source.source_id and p.verbatim_text.strip()
    }
    if source.coverage == CoverageStatus.unavailable or not evidence:
        assessment.explanation = "No passages from the cited source were available for assessment."
        return assessment

    try:
        result = await classify_claim_gemini(
            claim.normalized_text, list(evidence.values()), source.coverage.value, source.matched_title or "", source.newer_works
        )
        flags = result["issue_flags"]
        explanation = result["explanation"]
        passage_ids = result["evidence_passage_ids"]
        verdict = result["verdict"]
        if (
            not isinstance(flags, list) or not all(isinstance(flag, str) for flag in flags)
            or not isinstance(explanation, str) or not explanation.strip()
            or not isinstance(passage_ids, list)
            or not all(isinstance(pid, str) for pid in passage_ids)
        ):
            raise ValueError("Invalid assessment response")
        if "provider_error" in flags:
            raise ValueError("Evidence provider failed")
        verdict = SemanticVerdict(verdict) if verdict is not None else None
    except Exception:
        assessment.assessment_status = AssessmentStatus.failed
        assessment.explanation = "The evidence provider could not complete this assessment."
        assessment.issue_flags.append("provider_error")
        return assessment

    assessment.issue_flags.extend(flags)
    assessment.explanation = explanation
    if verdict == SemanticVerdict.POSSIBLY_OUTDATED:
        assessment.explanation = "A newer publication must substantiate a freshness flag."
        return assessment
    if verdict is None:
        return assessment
    if not passage_ids or any(pid not in evidence for pid in passage_ids):
        assessment.explanation = "The proposed verdict could not be traced to retrieved passages."
        return assessment
    if verdict == SemanticVerdict.UNSUPPORTED and source.coverage != CoverageStatus.full_text:
        assessment.explanation = "The available source text is too limited to determine whether it supports the claim."
        return assessment

    assessment.assessment_status = AssessmentStatus.assessed
    assessment.semantic_verdict = verdict
    assessment.evidence_passage_ids = list(dict.fromkeys(passage_ids))
    assessment.confidence_basis = ("Full-text passage from the matched paper." if source.coverage == CoverageStatus.full_text
                                   else "Only part of the matched paper was available.")
    quote = result.get("update_quote")
    reason = result.get("update_reason")
    if verdict in (SemanticVerdict.SUPPORTED, SemanticVerdict.PARTLY_SUPPORTED):
        for work in source.newer_works:
            if (work["url"] == result.get("update_url") and isinstance(quote, str)
                    and len(quote.strip()) >= 20 and quote in work["text"] and isinstance(reason, str) and reason.strip()):
                assessment.semantic_verdict = SemanticVerdict.POSSIBLY_OUTDATED
                assessment.update_evidence = {k: work[k] for k in ("url", "title", "year")}
                assessment.update_evidence["quote"] = quote
                assessment.explanation += " " + reason
                assessment.issue_flags.append("Review newer evidence")
                break
    return assessment
