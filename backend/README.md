# veriCite evidence discovery backend

This is an initial **academic discovery** API, not yet a claim-verification system.
Results are candidate papers; they must be read and evaluated before assigning verdicts.

## Setup

```bash
cd backend
python -m venv .venv
# Windows:
.venv\\Scripts\\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn main:app --reload
```

Open http://localhost:8000/docs for interactive API documentation.

- `GET /api/health` — configured search providers
- `GET /api/evidence/search?q=climate%20change&limit=5` — parallel search
- `GET /api/evidence/search?q=diabetes&providers=pubmed,europe_pmc` — selected sources
- `GET /api/evidence/open-access?doi=10.1038/nature12373` — Unpaywall DOI lookup (requires email)

### Providers

OpenAlex, Semantic Scholar, Crossref, PubMed, Europe PMC and arXiv have working integration code.
Unpaywall resolves DOI open-access locations. Other specialist sources (CORE, AGRIS,
OpenCitations, RePEc, Crossmark) are not yet implemented and need separate API-contract,
authentication and/or data-model work.

Some providers enforce rate limits or API keys; errors are returned under
`provider_errors` without failing the entire search. For production, add caching,
retry/backoff, request authentication, monitoring and normalized identifiers.

Never commit `.env` or API keys. This initial implementation does not upload PDFs,
extract claims, download full texts or use AI to verify them.

### Deterministic checks

From the repository root, run `python -m unittest discover -s backend -p 'test_*.py' -v`.
These tests mock provider responses; passing tests do not establish live provider availability.
If your environment requires a SOCKS proxy, install the optional HTTPX dependency with
`pip install 'httpx[socks]'` before making network requests.

## Verification pipeline scaffold

| Package | Input | Planned output |
|---|---|---|
| app/ingestion | PDF, DOCX, LaTeX or raw text | Addressable document blocks, tables, section headers and page or text locations |
| app/extraction | Document blocks with original citation markers | Bibliography, atomic claims and claim–reference links, including ambiguous grouped citations |
| app/resolution | Unique bibliography entries | Candidate matches, field mismatches, canonical source ID, retraction and access information |
| app/retrieval | Resolved source and atomic claim | Ranked passages from that specific source, with verbatim text and page or table locations |
| app/verification | One claim–paper pair and its evidence | Support verdict or reason to abstain, issue flags, evidence IDs and review status |
| app/reporting | Results and incomplete assessments | Manuscript-level counts, traceable per-claim results and review flags |
| app/providers | Requests from pipeline stages | Gemini extraction and classification, Crossref identity matching, OpenAlex source discovery, Semantic Scholar fallback |

## Planned API contract

- `POST /verifications` accepts a manuscript and returns a job ID.
- `GET /verifications/{id}` returns processing status or the final report.

The verification job endpoints above are planned. Both `uvicorn main:app` and `uvicorn app.main:app` serve the discovery API and `/health` from the backend directory.

## Run on Render

For an existing Python web service using the repository root, use these settings.

| Setting | Value |
|---|---|
| Root Directory | Leave blank |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `uvicorn main:app --host 0.0.0.0 --port $PORT` |
| Health Check Path | `/api/health` |

Set `GEMINI_API_KEY` and `GEMINI_MODEL` in the backend service environment for
live claim extraction and assessment. Contact details and optional provider
settings are listed in `.env.example`.


### CORE works search

Set `CORE_API_KEY` in `backend/.env` for local development or in the backend
service environment for deployment. Get a key from [CORE](https://core.ac.uk/services/api).
The backend includes CORE in default discovery when the key is configured.

Use `GET /api/evidence/search` with `providers=core` to search CORE alone.
Pass a claim, free text, or a CORE query in the URL-encoded `q` parameter.

| Search | Example `q` |
| --- | --- |
| Title | `title:"machine learning"` |
| DOI | `doi:"10.1038/nature14539"` |
| Author | `authors:"Yann LeCun"` |
| Publication year | `title:"deep learning" AND yearPublished>=2020` |

CORE results include authors, publication year, DOI, abstract and, when
available, a full-text download link. `has_full_text` reflects the information
CORE returned. Discovery results are candidates for review.
