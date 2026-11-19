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
