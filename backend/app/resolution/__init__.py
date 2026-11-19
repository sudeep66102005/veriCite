"""Stage 3 – Reference Resolution.

For each unique Reference, attempts to resolve it to a canonical paper
identity using Crossref (DOI look-up and bibliographic search), OpenAlex,
and Semantic Scholar, in that priority order.
"""
from __future__ import annotations

import asyncio
import difflib
import html
import re
import uuid
from urllib.parse import quote

import httpx

from app.config import (
    CROSSREF_MAILTO,
    OPENALEX_API_KEY,
    OPENALEX_EMAIL,
    PROVIDER_TIMEOUT,
    SEMANTIC_SCHOLAR_API_KEY,
    UNPAYWALL_EMAIL,
)
from integrations.providers import openalex_abstract
from app.models import CoverageStatus, IdentityStatus, Reference, ResolvedSource

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _doi(value: str | None) -> str | None:
    doi = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", (value or "").strip(), flags=re.I)
    return doi.casefold() if doi else None


def _title_similarity(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0
    left, right = (" ".join(re.findall(r"\w+", title.casefold())) for title in (a, b))
    return difflib.SequenceMatcher(None, left, right).ratio()


def _extract_surnames(names: list[str]) -> set[str]:
    """Return a set of lower-case surnames extracted from a list of author strings."""
    surnames: set[str] = set()
    for name in names:
        if not name.strip():
            continue
        # "Family, Given" or "Given Family"
        parts = name.split(",")
        surname = parts[0].strip() if len(parts) >= 2 else name.strip().split()[-1]
        surnames.add(surname.lower())
    return surnames


def _parse_crossref_work(item: dict) -> tuple[str | None, list[str], int | None, str | None]:
    """Return (title, authors, year, doi) from a Crossref work item."""
    titles = item.get("title") or []
    title = None
    if titles:
        components = [titles[0], *(item.get("subtitle") or [])]
        title = " ".join(html.unescape(re.sub(r"<[^>]+>", "", part)).strip() for part in components)
    raw_authors = item.get("author") or []
    authors: list[str] = []
    for a in raw_authors:
        family = a.get("family", "")
        given = a.get("given", "")
        if a.get("name"):
            authors.append(a["name"])
        elif family:
            authors.append(f"{family}, {given}".strip(", "))
    year: int | None = None
    dp = (item.get("published") or {}).get("date-parts")
    if dp and dp[0]:
        try:
            year = int(dp[0][0])
        except (ValueError, TypeError, IndexError):
            pass
    doi = _doi(item.get("DOI"))
    return title, authors, year, doi


# ---------------------------------------------------------------------------
# Step 1 – DOI look-up via Crossref
# ---------------------------------------------------------------------------

async def _crossref_doi_lookup(
    doi: str, client: httpx.AsyncClient
) -> tuple[IdentityStatus, str | None, str | None, list[str], int | None, str | None]:
    """Return (status, mismatch_note, title, authors, year, canonical_doi)."""
    url = f"https://api.crossref.org/works/{quote(doi, safe='/')}"
    params: dict = {}
    if CROSSREF_MAILTO:
        params["mailto"] = CROSSREF_MAILTO
    try:
        resp = await client.get(url, params=params, timeout=PROVIDER_TIMEOUT)
        payload = resp.json() if resp.is_success else {}
    except (httpx.HTTPError, ValueError):
        return IdentityStatus.lookup_failed, None, None, [], None, None

    if resp.status_code == 404:
        return IdentityStatus.unresolved, None, None, [], None, None  # caller tries bibliographic

    if resp.status_code != 200:
        return IdentityStatus.lookup_failed, None, None, [], None, None

    data = payload.get("message") or {}
    if not isinstance(data, dict) or not data.get("DOI"):
        return IdentityStatus.lookup_failed, None, None, [], None, None
    title, authors, year, canonical_doi = _parse_crossref_work(data)
    return IdentityStatus.matched, None, title, authors, year, canonical_doi or doi


# ---------------------------------------------------------------------------
# Step 2 – Bibliographic search via Crossref
# ---------------------------------------------------------------------------

async def _crossref_bib_search(
    ref: Reference, client: httpx.AsyncClient
) -> tuple[IdentityStatus, str | None, list[str], int | None, str | None]:
    """Return (status, title, authors, year, canonical_doi)."""
    query_parts = [ref.title or ""]
    if ref.authors:
        query_parts.extend(ref.authors[:2])
    if ref.year:
        query_parts.append(str(ref.year))
    query = " ".join(p for p in query_parts if p).strip()

    url = "https://api.crossref.org/works"
    params: dict = {
        "query.bibliographic": query,
        "rows": 3,
        "mailto": CROSSREF_MAILTO or "",
    }
    try:
        resp = await client.get(url, params=params, timeout=PROVIDER_TIMEOUT)
        payload = resp.json() if resp.is_success else {}
    except (httpx.HTTPError, ValueError):
        return IdentityStatus.lookup_failed, None, [], None, None

    if resp.status_code != 200:
        return IdentityStatus.lookup_failed, None, [], None, None

    items = (payload.get("message") or {}).get("items") or []
    matches = {}
    for item in items:
        title, authors, year, doi = _parse_crossref_work(item)
        if doi and _matches_reference(ref, title, authors, year):
            matches[doi] = (title, authors, year, doi)

    if len(matches) == 1:
        return (IdentityStatus.matched, *next(iter(matches.values())))
    status = IdentityStatus.ambiguous if matches else IdentityStatus.unresolved
    return status, None, [], None, None


# ---------------------------------------------------------------------------
# Step 3 – OpenAlex lookup
# ---------------------------------------------------------------------------

def _matches_reference(ref: Reference, title: str | None, authors: list[str], year: int | None) -> bool:
    if ref.title and _title_similarity(ref.title, title) < 0.86:
        return False
    if ref.year and year and abs(ref.year - year) > 1:
        return False
    if ref.authors and authors and not (_extract_surnames(ref.authors) & _extract_surnames(authors)):
        return False
    return bool(title)


async def _provider_json(client: httpx.AsyncClient, url: str, params: dict, headers: dict | None = None) -> dict:
    try:
        response = await client.get(url, params=params, headers=headers, timeout=PROVIDER_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {}
    except (httpx.HTTPError, ValueError):
        return {}


async def _openalex_lookup(ref: Reference, doi: str | None, client: httpx.AsyncClient) -> list[dict]:
    base = "https://api.openalex.org/works"
    params = {}
    if OPENALEX_API_KEY:
        params["api_key"] = OPENALEX_API_KEY
    if OPENALEX_EMAIL:
        params["mailto"] = OPENALEX_EMAIL
    if doi:
        work = await _provider_json(client, f"{base}/https://doi.org/{quote(doi, safe='/')}", params)
        if _doi(work.get("doi")) == doi:
            return [work]
    if not ref.title or doi:
        return []
    result = await _provider_json(client, base, {**params, "search": ref.title, "per-page": 5})
    return result.get("results") or []


async def semantic_scholar_works(ref: Reference, doi: str | None, client: httpx.AsyncClient) -> list[dict]:
    base = "https://api.semanticscholar.org/graph/v1/paper"
    params = {"fields": "title,authors,year,url,externalIds,openAccessPdf,abstract"}
    headers = {"x-api-key": SEMANTIC_SCHOLAR_API_KEY} if SEMANTIC_SCHOLAR_API_KEY else {}
    if doi:
        work = await _provider_json(client, f"{base}/DOI:{quote(doi, safe='/')}", params, headers)
        if _doi((work.get("externalIds") or {}).get("DOI")) == doi:
            return [work]
    if not ref.title or doi:
        return []
    result = await _provider_json(client, f"{base}/search", {**params, "query": ref.title, "limit": 5}, headers)
    return result.get("data") or []


async def unpaywall_pdf_urls(doi: str, client: httpx.AsyncClient) -> list[str]:
    email = UNPAYWALL_EMAIL.strip()
    if not email:
        return []
    work = await _provider_json(client, f"https://api.unpaywall.org/v2/{quote(doi, safe='/')}", {"email": email})
    if _doi(work.get("doi")) != doi:
        return []
    locations = [work.get("best_oa_location") or {}, *(work.get("oa_locations") or [])]
    return list(dict.fromkeys(location["url_for_pdf"] for location in locations if location.get("url_for_pdf")))


def match_provider_work(ref: Reference, doi: str | None, works: list[dict], provider: str) -> dict:
    matches = []
    for work in works:
        if provider == "openalex":
            authors = [(a.get("author") or {}).get("display_name") or "" for a in work.get("authorships") or []]
            title, year, candidate_doi = work.get("display_name") or work.get("title"), work.get("publication_year"), _doi(work.get("doi"))
        else:
            authors = [a.get("name") or "" for a in work.get("authors") or []]
            title, year, candidate_doi = work.get("title"), work.get("year"), _doi((work.get("externalIds") or {}).get("DOI"))
        if doi and candidate_doi != doi:
            continue
        if _matches_reference(ref, title, authors, year):
            matches.append({**work, "matched_metadata": (title, authors, year, candidate_doi)})
    return matches[0] if len(matches) == 1 else {}


async def resolve_reference(ref: Reference, client: httpx.AsyncClient) -> ResolvedSource:
    doi = _doi(ref.doi)
    source = ResolvedSource(
        source_id=f"src_{uuid.uuid4().hex[:12]}",
        ref_id=ref.ref_id,
        identity_status=IdentityStatus.unresolved,
        coverage=CoverageStatus.unavailable,
    )
    status = IdentityStatus.unresolved
    metadata = (None, [], None, None)
    if doi:
        status, _, title, authors, year, candidate_doi = await _crossref_doi_lookup(doi, client)
        if status == IdentityStatus.matched:
            if _doi(candidate_doi) != doi or not _matches_reference(ref, title, authors, year):
                source.canonical_doi = doi
                source.identity_status = IdentityStatus.metadata_mismatch
                return source
            metadata = (title, authors, year, doi)
    elif ref.title:
        status, *candidate = await _crossref_bib_search(ref, client)
        if status == IdentityStatus.matched:
            metadata = tuple(candidate)
    if status == IdentityStatus.matched:
        doi = metadata[3]

    openalex = match_provider_work(ref, doi, await _openalex_lookup(ref, doi, client), "openalex")
    if openalex:
        if status != IdentityStatus.matched:
            metadata = openalex["matched_metadata"]
            status = IdentityStatus.matched
            doi = metadata[3]
        source.openalex_id = openalex.get("id")
        work_id = (source.openalex_id or "").rsplit("/", 1)[-1]
        year = openalex.get("publication_year")
        if re.fullmatch(r"W[0-9]+", work_id) and isinstance(year, int):
            params = {"filter": f"cites:{work_id},from_publication_date:{year + 1}-01-01,has_abstract:true",
                      "sort": "publication_date:desc", "per-page": 3}
            if OPENALEX_API_KEY:
                params["api_key"] = OPENALEX_API_KEY
            later = await _provider_json(client, "https://api.openalex.org/works", params)
            for item in later.get("results") or []:
                abstract = openalex_abstract(item.get("abstract_inverted_index"))
                url = item.get("doi") or item.get("id") or ""
                if (abstract and url.startswith("https://") and not item.get("is_retracted")
                        and (item.get("publication_year") or 0) > year
                        and source.openalex_id in (item.get("referenced_works") or [])):
                    source.newer_works.append({"title": item.get("display_name") or url,
                                               "url": url, "year": str(item["publication_year"]),
                                               "text": abstract[:3000]})
        source.is_retracted = bool(openalex.get("is_retracted"))
        if source.is_retracted:
            source.retraction_note = "Flagged as retracted by OpenAlex"
        best = openalex.get("best_oa_location") or {}
        primary = openalex.get("primary_location") or {}
        locations = [best, primary, *(openalex.get("locations") or [])]
        source.pdf_urls = list(dict.fromkeys(
            location["pdf_url"] for location in locations if location.get("pdf_url") and (location is best or location.get("is_oa"))
        ))
        source.publication_url = primary.get("landing_page_url") or best.get("landing_page_url") or source.openalex_id
        source.abstract_text = openalex_abstract(openalex.get("abstract_inverted_index"))

    if status != IdentityStatus.matched:
        scholar = match_provider_work(ref, doi, await semantic_scholar_works(ref, doi, client), "scholar")
        if scholar:
            metadata = scholar["matched_metadata"]
            status = IdentityStatus.matched
            source.s2_id = scholar.get("paperId")
            source.publication_url = scholar.get("url")
            pdf_url = (scholar.get("openAccessPdf") or {}).get("url")
            if pdf_url:
                source.pdf_urls.append(pdf_url)
            source.abstract_text = scholar.get("abstract")

    source.identity_status = status
    if status == IdentityStatus.matched:
        source.matched_title, source.matched_authors, source.matched_year, source.canonical_doi = metadata
        source.source_url = next(iter(source.pdf_urls), None)
    return source


# ---------------------------------------------------------------------------
# Batch resolver with deduplication
# ---------------------------------------------------------------------------

def _ref_key(ref: Reference) -> tuple:
    """Canonical key for deduplication."""
    return (_doi(ref.doi), (ref.title or "").casefold().strip(), ref.year, tuple(ref.authors))


async def resolve_all_references(refs: list[Reference]) -> list[ResolvedSource]:
    """Resolve all references with deduplication and concurrency limit of 3."""
    sem = asyncio.Semaphore(3)

    # Deduplicate: keep one canonical ref per key, but remember all ref_ids
    unique: dict[tuple, Reference] = {}
    duplicates: dict[tuple, list[str]] = {}  # canonical key → list of duplicate ref_ids

    for ref in refs:
        key = _ref_key(ref)
        if key not in unique:
            unique[key] = ref
            duplicates[key] = []
        else:
            duplicates[key].append(ref.ref_id)

    results: list[ResolvedSource] = []

    async def _resolve_one(key: tuple, ref: Reference, client: httpx.AsyncClient) -> None:
        async with sem:
            resolved = await resolve_reference(ref, client)
        results.append(resolved)
        # Emit cloned sources for duplicate refs (same paper, different ref_ids)
        for dup_ref_id in duplicates[key]:
            dup = resolved.model_copy(
                update={
                    "source_id": f"src_{uuid.uuid4().hex[:12]}",
                    "ref_id": dup_ref_id,
                }
            )
            results.append(dup)

    async with httpx.AsyncClient(follow_redirects=True) as client:
        tasks = [
            asyncio.create_task(_resolve_one(key, ref, client))
            for key, ref in unique.items()
        ]
        await asyncio.gather(*tasks)

    return results
