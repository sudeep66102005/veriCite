"""Stage 4 – Source Retrieval and Passage Ranking.

Downloads each ResolvedSource (PDF or abstract), parses it with Docling,
embeds the resulting passages with sentence-transformers, and returns the
most relevant passages ranked against the supplied claim texts.
"""
from __future__ import annotations

import asyncio
import re
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Optional

import httpx
import numpy as np

from app.config import (
    EMBEDDING_MODEL, MAX_DOWNLOAD_SIZE_MB, PROVIDER_TIMEOUT,
)
from app.models import CoverageStatus, DocumentBlock, IdentityStatus, Passage, Reference, ResolvedSource
from app.resolution import match_provider_work, semantic_scholar_works, unpaywall_pdf_urls

# ---------------------------------------------------------------------------
# Module-level embedding model cache
# ---------------------------------------------------------------------------

_embedding_model = None
_embedding_lock = threading.Lock()


def get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer

        _embedding_model = SentenceTransformer(EMBEDDING_MODEL)
    return _embedding_model


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LOGIN_SIGNALS = re.compile(r"login|sign in|access denied|please log in", re.IGNORECASE)
_NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\s*(?:%|mg|kg|ml|l|km|m|cm|mm|g|s|ms|µ[a-z]*)?\b")


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def _lexical_boost(claim: str, passage_text: str) -> float:
    """Return +0.1 if the passage shares numbers, units, or key content words with the claim."""
    claim_numbers = set(_NUMBER_RE.findall(claim.lower()))
    passage_numbers = set(_NUMBER_RE.findall(passage_text.lower()))
    if claim_numbers & passage_numbers:
        return 0.1

    claim_words = set(re.findall(r"\b[a-z]{4,}\b", claim.lower()))
    passage_words = set(re.findall(r"\b[a-z]{4,}\b", passage_text.lower()))
    overlap = claim_words & passage_words
    # At least 3 meaningful content words shared
    if len(overlap) >= 3:
        return 0.05
    return 0.0


def _chunk_abstract(text: str) -> list[str]:
    """Preserve source punctuation and short findings when returning quoted evidence."""
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

async def _download_pdf(
    source_url: str, client: httpx.AsyncClient
) -> tuple[Path | None, str]:
    """Download URL → temp file. Returns (path, status) where status is 'ok', 'login', 'size', 'type', 'error'."""
    max_bytes = MAX_DOWNLOAD_SIZE_MB * 1024 * 1024
    try:
        async with client.stream(
            "GET", source_url, follow_redirects=True, timeout=PROVIDER_TIMEOUT
        ) as resp:
            if resp.status_code != 200:
                return None, "error"

            content_length = resp.headers.get("content-length")
            if content_length and int(content_length) > max_bytes:
                return None, "size"

            content_type = resp.headers.get("content-type", "").lower()

            # HTML check: may be login page
            if "text/html" in content_type:
                # Read first 2000 bytes to check
                chunk_data = b""
                async for chunk in resp.aiter_bytes(chunk_size=2048):
                    chunk_data += chunk
                    break
                snippet = chunk_data[:2000].decode("utf-8", errors="replace")
                if _LOGIN_SIGNALS.search(snippet):
                    return None, "login"
                return None, "type"

            is_pdf = (
                "application/pdf" in content_type
                or "application/octet-stream" in content_type
                or "pdf" in content_type
            )
            if not is_pdf:
                return None, "type"

            # Stream to temp file
            suffix = ".pdf"
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            downloaded = 0
            async for chunk in resp.aiter_bytes(chunk_size=65536):
                downloaded += len(chunk)
                if downloaded > max_bytes:
                    tmp.close()
                    Path(tmp.name).unlink(missing_ok=True)
                    return None, "size"
                tmp.write(chunk)
            tmp.close()
            return Path(tmp.name), "ok"

    except httpx.TimeoutException:
        return None, "timeout"
    except (httpx.ConnectError, Exception):
        return None, "error"


# ---------------------------------------------------------------------------
# Docling parse
# ---------------------------------------------------------------------------

def _parse_pdf(tmp_path: Path) -> list[tuple[str, str | None, int | None, str | None]]:
    """Read selectable source text and preserve the printed PDF page location."""
    import pymupdf

    chunks = []
    section = None
    with pymupdf.open(tmp_path) as document:
        if document.needs_pass:
            return []
        for page in document:
            for block in page.get_text("blocks", sort=True):
                if block[6] != 0:
                    continue
                text = block[4].strip()
                if re.fullmatch(r"(?:[0-9.]+\s*)?(?:abstract|introduction|results|discussion|methods|conclusions?|limitations|references)", text, re.I):
                    section = text
                elif len(text) >= 20:
                    # Preserve verbatim excerpts while bounding individual model inputs.
                    for start in range(0, len(text), 2000):
                        chunks.append((text[start:start + 2000], section, page.number + 1, None))
    return chunks


# ---------------------------------------------------------------------------
# Embedding and ranking
# ---------------------------------------------------------------------------

def _embed_texts(texts: list[str]) -> np.ndarray:
    with _embedding_lock:
        model = get_embedding_model()
        return model.encode(texts, convert_to_numpy=True, show_progress_bar=False)


def _lexical_rank(passages, claims_text, top_k):
    # Weight terms by rarity in this paper, including numbers and units.
    from collections import Counter
    from math import log1p
    tokens = [set(re.findall(r"\w+", p.verbatim_text.casefold())) for p in passages]
    frequency = Counter(term for terms in tokens for term in terms)
    queries = [set(re.findall(r"\w+", claim.casefold())) for claim in claims_text]
    weights = {term: log1p(len(passages) / count) for term, count in frequency.items()}
    scores = [max(sum(weights[t] for t in terms & query) for query in queries) for terms in tokens]
    indices = sorted(range(len(passages)), key=scores.__getitem__, reverse=True)[:top_k]
    return [passages[i] for i in indices]


def _rank_passages(
    passages: list[Passage],
    claims_text: list[str],
    top_k: int = 10,
) -> list[Passage]:
    if len(passages) <= top_k or not claims_text:
        return passages
    if not EMBEDDING_MODEL:
        return _lexical_rank(passages, claims_text, top_k)

    passage_texts = [p.verbatim_text for p in passages]
    passage_embeddings = _embed_texts(passage_texts)

    # Store embeddings back into passages
    for i, p in enumerate(passages):
        p.embedding = passage_embeddings[i].tolist()

    # Score each passage per claim, accumulate max
    scores = np.zeros(len(passages))

    claims_text = list(dict.fromkeys(claims_text))
    for claim, claim_emb in zip(claims_text, _embed_texts(claims_text)):
        for i, (p_emb, passage) in enumerate(zip(passage_embeddings, passages)):
            sim = _cosine_similarity(claim_emb, p_emb)
            boost = _lexical_boost(claim, passage.verbatim_text)
            combined = sim + boost
            scores[i] = max(scores[i], combined)

    # Second pass: if max similarity is low, give a small metric-search boost
    max_sim = float(np.max(scores)) if len(scores) > 0 else 0.0
    if max_sim < 0.4:
        all_claim_text = " ".join(claims_text)
        metric_numbers = set(_NUMBER_RE.findall(all_claim_text))
        # Boost passages with matching metric names or section keywords
        section_keywords = set(re.findall(r"\b[a-z]{4,}\b", all_claim_text.lower()))
        for i, passage in enumerate(passages):
            p_text_lower = passage.verbatim_text.lower()
            p_numbers = set(_NUMBER_RE.findall(p_text_lower))
            p_words = set(re.findall(r"\b[a-z]{4,}\b", p_text_lower))
            if metric_numbers & p_numbers:
                scores[i] += 0.15
            elif len(section_keywords & p_words) >= 2:
                scores[i] += 0.05

    # Collect top-k by score (deduplicated by passage_id)
    ranked_indices = np.argsort(scores)[::-1]
    seen: set[str] = set()
    top_passages: list[Passage] = []

    for idx in ranked_indices:
        if len(top_passages) >= top_k:
            break
        p = passages[idx]
        if p.passage_id not in seen:
            seen.add(p.passage_id)
            top_passages.append(p)

    # Try to include contrary passages (similar topic, opposite direction)
    # Heuristic: passages in the bottom half that have high lexical overlap with top passages
    if len(top_passages) > 0 and len(passages) > top_k:
        contrary_re = re.compile(
            r"\b(however|although|contrary|in contrast|despite|on the other hand|but|yet|whereas)\b",
            re.IGNORECASE,
        )
        for idx in ranked_indices[top_k:]:
            if len(top_passages) >= top_k + 2:
                break
            p = passages[idx]
            if p.passage_id not in seen and contrary_re.search(p.verbatim_text):
                seen.add(p.passage_id)
                top_passages.append(p)

    return top_passages


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def retrieve_source(
    source: ResolvedSource,
    claims_text: list[str],
    client: httpx.AsyncClient,
) -> tuple[ResolvedSource, list[Passage]]:
    """Download, parse, embed, and rank passages for a single ResolvedSource."""

    if source.identity_status != IdentityStatus.matched:
        return source, []

    raw_chunks: list[tuple[str, str | None, int | None, str | None]] = []
    passages: list[Passage] = []
    coverage = CoverageStatus.unavailable
    abstract = source.abstract_text
    selected_url = None
    publication_url = source.publication_url

    attempted: set[str] = set()

    async def try_pdfs(urls: list[str]) -> None:
        nonlocal raw_chunks, selected_url, coverage
        for url in urls:
            if raw_chunks:
                return
            if url in attempted or len(attempted) >= 6:
                continue
            attempted.add(url)
            path, _ = await _download_pdf(url, client)
            if path is None:
                continue
            try:
                raw_chunks = await asyncio.to_thread(_parse_pdf, path)
            except Exception:
                continue
            finally:
                path.unlink(missing_ok=True)
            if raw_chunks:
                selected_url = url
                coverage = CoverageStatus.full_text

    await try_pdfs((source.pdf_urls or ([source.source_url] if source.source_url else []))[:3])
    if not raw_chunks and source.canonical_doi:
        await try_pdfs((await unpaywall_pdf_urls(source.canonical_doi, client))[:2])
    if not raw_chunks and not source.s2_id:
        ref = Reference(
            ref_id=source.ref_id, document_id="", raw_entry="",
            title=source.matched_title, authors=source.matched_authors, year=source.matched_year,
        )
        scholar = match_provider_work(ref, source.canonical_doi, await semantic_scholar_works(ref, source.canonical_doi, client), "scholar", verified_doi=True)
        if scholar:
            abstract = abstract or scholar.get("abstract")
            publication_url = publication_url or scholar.get("url")
            pdf = (scholar.get("openAccessPdf") or {}).get("url")
            if pdf:
                await try_pdfs([pdf])

    if not raw_chunks and abstract:
        raw_chunks = [(sentence, "Abstract", None, None) for sentence in _chunk_abstract(abstract)]
        if raw_chunks:
            coverage = CoverageStatus.abstract_only

    # ------------------------------------------------------------------
    # Step 3 – Create Passage objects
    # ------------------------------------------------------------------
    for chunk_text, section, page, table_context in raw_chunks:
        passages.append(
            Passage(
                passage_id=f"p_{uuid.uuid4().hex[:12]}",
                source_id=source.source_id,
                verbatim_text=chunk_text,
                section=section,
                page=page,
                char_start=None,
                char_end=None,
                table_context=table_context,
                embedding=None,  # filled in step 4
            )
        )

    # ------------------------------------------------------------------
    # Step 4 – Embed and rank
    # ------------------------------------------------------------------
    if claims_text:
        try:
            passages = await asyncio.to_thread(_rank_passages, passages, claims_text, top_k=10)
        except Exception:
            passages = _lexical_rank(passages, claims_text, 10)

    updated = source.model_copy(update={
        "coverage": coverage, "source_url": selected_url, "publication_url": publication_url,
    })
    return updated, passages


# ---------------------------------------------------------------------------
# Batch retrieval
# ---------------------------------------------------------------------------

async def retrieve_all_sources(
    sources: list[ResolvedSource],
    claims_text: list[str],
    max_concurrent: int = 3,
) -> tuple[list[ResolvedSource], list[Passage]]:
    """Retrieve and rank passages for all sources concurrently."""
    sem = asyncio.Semaphore(max_concurrent)
    updated_sources: list[ResolvedSource] = []
    all_passages: list[Passage] = []

    async def _retrieve_one(source: ResolvedSource, client: httpx.AsyncClient) -> None:
        async with sem:
            updated, passages = await retrieve_source(source, claims_text, client)
        updated_sources.append(updated)
        all_passages.extend(passages)

    async with httpx.AsyncClient(follow_redirects=True) as client:
        tasks = [
            asyncio.create_task(_retrieve_one(source, client))
            for source in sources
            if source.identity_status.value in ("matched", "ambiguous")
        ]
        # Sources that couldn't be resolved still get coverage=unavailable
        for source in sources:
            if source.identity_status.value not in ("matched", "ambiguous"):
                updated_sources.append(
                    source.model_copy(update={"coverage": CoverageStatus.unavailable})
                )
        await asyncio.gather(*tasks, return_exceptions=True)

    return updated_sources, all_passages
