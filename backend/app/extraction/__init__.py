"""Stage 2: extract references and map atomic claims to citation markers.

Public API
----------
parse_references(blocks)                   -> list[Reference]
detect_citation_markers(block, refs)       -> list[tuple]
extract_claims_and_links(blocks, refs)     -> (claims, links, issues)
"""
from __future__ import annotations

import asyncio
import re
import uuid

from app.providers import ExtractionProviderError, extract_claims_gemini
from app.models import (
    BlockType,
    Claim,
    ClaimReferenceLink,
    DocumentBlock,
    MappingStatus,
    Reference,
)

# ---------------------------------------------------------------------------
# Regex helpers
# ---------------------------------------------------------------------------

_DOI_RE = re.compile(r"10\.\d{4,}/\S+")
_YEAR_RE = re.compile(r"\b(1[9][0-9]{2}|20[0-9]{2})\b")

# Numeric citation: [1], [2,5], [2-5], [2–7]
_NUMERIC_CITE_RE = re.compile(
    r"\[(\d{1,6}(?:\s*[-–]\s*\d{1,6})?(?:\s*,\s*\d{1,6}(?:\s*[-–]\s*\d{1,6})?)*)\]"
)

# Author-year inline: (Smith et al., 2021; Jones, 2019) or (Smith 2021)
_AUTHOR_YEAR_RE = re.compile(
    r"\(([A-Z][a-z]+(?:\s+et\s+al\.)?(?:,?\s*\d{4}[a-z]?)(?:;\s*[A-Z][a-z]+"
    r"(?:\s+et\s+al\.)?(?:,?\s*\d{4}[a-z]?)*)*)\)"
)
# Narrative author-year: Smith et al. (2021)
_NARRATIVE_AY_RE = re.compile(
    r"([A-Z][a-z]+(?:\s+et\s+al\.)?)\s+\((\d{4}[a-z]?)\)"
)

# LaTeX: \cite{key}, \citep{key1,key2}, \citet{key}
_LATEX_CITE_RE = re.compile(r"\\cite[pt]?\{([^}]+)\}")

# Sentence splitter (naive but sufficient for clause extraction)
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _expand_range(start: int, end: int) -> list[int]:
    return list(range(start, end + 1)) if 0 <= end - start < 100 else []


def _expand_numeric_marker(marker_text: str) -> list[int]:
    """Expand '2,5', '2-7', '2–7' into a list of ints."""
    nums: list[int] = []
    # Replace en-dash with hyphen
    marker_text = marker_text.replace("–", "-")
    # Split on commas (handle spaces)
    parts = re.split(r",\s*", marker_text)
    for part in parts:
        part = part.strip()
        m = re.match(r"(\d+)\s*[-]\s*(\d+)$", part)
        if m:
            expanded = _expand_range(int(m.group(1)), int(m.group(2)))
            if not expanded:
                return []
            nums.extend(expanded)
        elif part.isdigit():
            nums.append(int(part))
    return nums


def _get_sentence_containing(text: str, char_pos: int) -> str:
    """Return the sentence from *text* that contains character position *char_pos*."""
    start = 0
    for boundary in _SENT_SPLIT_RE.finditer(text):
        if boundary.start() > char_pos:
            return text[start:boundary.start()].strip()
        start = boundary.end()
    return text[start:].strip()


# ---------------------------------------------------------------------------
# Function 1: parse_references
# ---------------------------------------------------------------------------


def parse_references(blocks: list[DocumentBlock]) -> list[Reference]:
    """Parse bibliography blocks into Reference objects."""
    bib_blocks = [b for b in blocks if b.block_type == BlockType.bibliography]
    if not bib_blocks:
        return []

    document_id = bib_blocks[0].document_id

    # Collect all raw text
    raw_text = "\n".join(b.text for b in bib_blocks)

    # Split into individual entries
    entries = _split_bib_entries(raw_text)

    refs: list[Reference] = []
    for idx, entry in enumerate(entries):
        entry = entry.strip()
        if not entry:
            continue
        ref_id = f"{document_id}_r{idx:04d}"
        raw_marker = _extract_raw_marker(entry, idx)
        doi = _extract_doi(entry)
        year = _extract_year(entry)
        authors = _extract_authors(entry, year)
        title = _extract_title(entry, authors, year)

        refs.append(
            Reference(
                ref_id=ref_id,
                document_id=document_id,
                raw_entry=entry,
                title=title,
                authors=authors,
                year=year,
                doi=doi,
                raw_marker=raw_marker,
            )
        )
    return refs


def _split_bib_entries(text: str) -> list[str]:
    """Split a bibliography text into individual reference entries."""
    # Try numbered list patterns first: [1] or 1. at start of line
    numbered_bracket = re.split(r"\n(?=\[\d+\])", text)
    if len(numbered_bracket) > 1:
        return numbered_bracket

    numbered_dot = re.split(r"\n(?=\d+\.)", text)
    if len(numbered_dot) > 1:
        return numbered_dot

    # Fallback: split on blank lines
    blank_split = re.split(r"\n{2,}", text)
    if len(blank_split) > 1:
        return blank_split

    # Last resort: one entry per line
    return text.splitlines()


def _extract_raw_marker(entry: str, fallback_idx: int) -> str | None:
    m = re.match(r"^\[(\d+)\]", entry.strip())
    if m:
        return f"[{m.group(1)}]"
    m2 = re.match(r"^(\d+)\.", entry.strip())
    if m2:
        return f"[{m2.group(1)}]"
    return None


def _extract_doi(entry: str) -> str | None:
    m = _DOI_RE.search(entry)
    if not m:
        return None
    doi = m.group(0).rstrip(".,;)")
    return doi


def _extract_year(entry: str) -> int | None:
    m = _YEAR_RE.search(entry)
    return int(m.group(0)) if m else None


def _extract_authors(entry: str, year: int | None) -> list[str]:
    """Heuristic: take text before the year (or first period) as authors."""
    # Strip leading marker
    text = re.sub(r"^\[?\d+\]?\.?\s*", "", entry.strip())
    if year:
        idx = text.find(str(year))
        if idx > 0:
            author_part = text[:idx]
        else:
            author_part = text.split(".")[0]
    else:
        author_part = text.split(".")[0]

    # Split on ; or , but keep name units together
    # Heuristic: each author is "Lastname, Initials" or "Firstname Lastname"
    raw_names = re.split(r";\s*|\band\b", author_part)
    authors: list[str] = []
    for name in raw_names:
        name = re.sub(r"\bet al\.?.*$", "", name).strip(" ,(.")
        if name and len(name) > 2:
            authors.append(name)
    return authors[:10]  # cap at 10


def _extract_title(entry: str, authors: list[str], year: int | None) -> str | None:
    """Heuristic title extraction: text between year and journal/DOI."""
    text = entry
    # Remove leading marker
    text = re.sub(r"^\[?\d+\]?\.?\s*", "", text.strip())

    # Try quoted title
    m = re.search(r'"([^"]{10,})"', text)
    if m:
        return m.group(1).strip()

    # After year, take up to next period or volume indicator
    if year:
        idx = text.find(str(year))
        if idx >= 0:
            after_year = text[idx + 4:].lstrip(").,: ")
            # Title ends at next period (but not initials) or at DOI
            title_candidate = re.split(r"\.\s+[A-Z]", after_year)
            if title_candidate:
                candidate = title_candidate[0].strip().rstrip(".,")
                if 5 < len(candidate) < 300:
                    return candidate
    return None


# ---------------------------------------------------------------------------
# Function 2: detect_citation_markers
# ---------------------------------------------------------------------------


def detect_citation_markers(
    block: DocumentBlock,
    refs: list[Reference],
) -> list[tuple[str, int, int, list[str]]]:
    """Return list of (marker_text, char_start, char_end, matched_ref_ids)."""
    text = block.text
    results: list[tuple[str, int, int, list[str]]] = []

    # Build lookup indices
    # Numeric marker → ref_id
    marker_to_ref: dict[str, list[str]] = {}
    for ref in refs:
        if ref.raw_marker:
            marker_to_ref.setdefault(ref.raw_marker, []).append(ref.ref_id)

    # 1) Numeric citations
    for m in _NUMERIC_CITE_RE.finditer(text):
        marker_text = m.group(0)
        nums = _expand_numeric_marker(m.group(1))
        matched_ids: list[str] = []
        for n in nums:
            key = f"[{n}]"
            if key in marker_to_ref:
                matched_ids.extend(marker_to_ref[key])
            else:
                matched_ids = []
                break
        results.append((marker_text, m.start(), m.end(), matched_ids))

    # 2) Author-year (parenthetical)
    for m in _AUTHOR_YEAR_RE.finditer(text):
        marker_text = m.group(0)
        inner = m.group(1)
        matched_ids = _resolve_author_year_inner(inner, refs)
        results.append((marker_text, m.start(), m.end(), matched_ids))

    # 3) Narrative author-year: Smith et al. (2021)
    for m in _NARRATIVE_AY_RE.finditer(text):
        marker_text = m.group(0)
        surname = m.group(1).split()[0]
        year_str = m.group(2)
        matched_ids = _resolve_surname_year(surname, year_str, refs)
        results.append((marker_text, m.start(), m.end(), matched_ids))

    # 4) LaTeX citations
    for m in _LATEX_CITE_RE.finditer(text):
        marker_text = m.group(0)
        keys = [k.strip() for k in m.group(1).split(",")]
        matched_ids = _resolve_latex_keys(keys, refs)
        results.append((marker_text, m.start(), m.end(), matched_ids))

    # De-duplicate by position (keep first match per span)
    seen_spans: set[tuple[int, int]] = set()
    deduped: list[tuple[str, int, int, list[str]]] = []
    for item in results:
        span = (item[1], item[2])
        if span not in seen_spans:
            seen_spans.add(span)
            deduped.append(item)

    return deduped


def _resolve_author_year_inner(inner: str, refs: list[Reference]) -> list[str]:
    """Resolve 'Smith et al., 2021; Jones, 2019' style string."""
    # Split on semicolons
    parts = re.split(r";\s*", inner)
    matched: list[str] = []
    for part in parts:
        part = part.strip()
        yr_m = _YEAR_RE.search(part)
        if not yr_m:
            continue
        year_str = yr_m.group(0)
        surname = part.split()[0].rstrip(",")
        ids = _resolve_surname_year(surname, year_str, refs)
        if not ids:
            return []
        matched.extend(ids)
    return matched


def _resolve_surname_year(surname: str, year_str: str, refs: list[Reference]) -> list[str]:
    """Match refs by first author surname and year."""
    year = int(re.sub(r"[a-z]$", "", year_str))
    matched: list[str] = []
    for ref in refs:
        if ref.year == year:
            for author in ref.authors[:1]:
                if surname.casefold() in re.findall(r"\w+", author.casefold()):
                    matched.append(ref.ref_id)
                    break
    return matched


def _resolve_latex_keys(keys: list[str], refs: list[Reference]) -> list[str]:
    matched: list[str] = []
    for key in keys:
        for ref in refs:
            if key in ref.ref_id or (ref.raw_entry and key in ref.raw_entry):
                matched.append(ref.ref_id)
                break
    return matched


# ---------------------------------------------------------------------------
# Function 3: extract_claims_and_links
# ---------------------------------------------------------------------------


async def extract_claims_and_links(
    blocks: list[DocumentBlock],
    refs: list[Reference],
) -> tuple[list[Claim], list[ClaimReferenceLink], list[str]]:
    """Stage 2 main: extract atomic claims and their reference links.

    Returns (claims, links, issues).
    """
    claims: list[Claim] = []
    links: list[ClaimReferenceLink] = []
    issues: list[str] = []

    for block in blocks:
        if block.block_type in (BlockType.bibliography, BlockType.heading):
            continue
        markers = sorted(detect_citation_markers(block, refs), key=lambda item: item[1])
        # Split at sentence boundaries, keeping author abbreviations such as "et al." intact.
        boundaries = [m.end() for m in _SENT_SPLIT_RE.finditer(block.text)
                      if not block.text[max(0,m.start()-8):m.start()].endswith(("et al.", "Fig.", "Dr.", "e.g."))]
        start = 0
        marker_index = 0
        for end in [*boundaries, len(block.text)]:
            sentence = block.text[start:end].strip()
            group = []
            while marker_index < len(markers) and markers[marker_index][1] < end:
                group.append(markers[marker_index])
                marker_index += 1
            offset = start
            start = end
            if not sentence or (not group and len(sentence.split()) < 3):
                continue
            # Cited entities are assessed per sentence. Uncited statements are
            # retained as review candidates, without guessing a bibliography entry.
            claim = Claim(claim_id=f"{block.document_id}_c{uuid.uuid4().hex[:12]}",
                          document_id=block.document_id, block_id=block.block_id,
                          original_span=sentence, normalized_text=sentence,
                          char_start=offset, char_end=end)
            if len(claims) >= 1000:
                raise ValueError("Manuscript exceeds the 1,000 candidate statement limit. Submit it in sections.")
            claims.append(claim)
            if not group:
                claim.mapping_issue = "Missing citation. Review this uncited statement."
                continue
            for marker, cs, ce, ids in group:
                ids = list(dict.fromkeys(ids))
                if not ids:
                    if marker not in claim.unmatched_markers:
                        claim.unmatched_markers.append(marker)
                    issues.append(f"Unmatched citation {marker} in claim {claim.claim_id}.")
                    continue
                ambiguous = len(ids) > 1 or len(group) > 1
                for rid in ids:
                    links.append(ClaimReferenceLink(
                        link_id=f"lnk_{uuid.uuid4().hex[:12]}", claim_id=claim.claim_id, ref_id=rid,
                        citation_marker=marker, marker_char_start=cs, marker_char_end=ce,
                        mapping_status=MappingStatus.ambiguous if ambiguous else MappingStatus.mapped,
                    ))
    # Split compound claims once per sentence, only after its mapping is certain.
    by_claim = {link.claim_id: link for link in links if link.mapping_status == MappingStatus.mapped}
    candidates = [c for c in claims if c.claim_id in by_claim and re.search(r"\b(?:and|but|whereas)\b|;", c.original_span, re.I)]
    slots = asyncio.Semaphore(2)
    async def split(claim):
        link = by_claim[claim.claim_id]
        try:
            async with slots:
                parts = await extract_claims_gemini(claim.original_span, link.citation_marker, [link.ref_id], claim.original_span)
        except ExtractionProviderError as exc:
            claim.extraction_error = str(exc)
            return []
        return [part for part in parts if part["original_span"] in claim.original_span
                and part["ref_ids"] == [link.ref_id]]
    for claim, parts in zip(candidates[:8], await asyncio.gather(*(split(c) for c in candidates[:8]))):
        if not parts:
            continue
        link = by_claim[claim.claim_id]
        for index, part in enumerate(parts[:10]):
            atom = claim if index == 0 else claim.model_copy(update={"claim_id": f"{claim.claim_id}_{index}"})
            atom.normalized_text = part["claim_text"]
            atom.original_span = part["original_span"]
            if index:
                claims.append(atom)
                links.append(link.model_copy(update={"claim_id": atom.claim_id, "link_id": f"{link.link_id}_{index}"}))
    return claims, links, issues
