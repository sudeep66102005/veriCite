# VeriCite verification and discovery API

FastAPI receives manuscript text extracted by the browser, maps claims to bibliography entries,
retrieves original publications and compares their passages with each claim. Jobs, source
evidence and assessments are stored in SQLite or PostgreSQL. Search endpoints also return candidate papers
for independent review. See the [workspace screenshot and architecture](../README.md).

## Local setup

Use Python 3.12. From the repository root, create and activate a virtual environment, install
`pip install -r requirements.txt`, and copy `backend/.env.example` to `backend/.env`.
Set `GEMINI_API_KEY` for live verification. Start the server with
`uvicorn main:app --no-proxy-headers --reload`. Interactive API documentation is at
`http://localhost:8000/docs`.

The root `main.py` is the ASGI entry point used by Render and root-level Uvicorn commands.
It imports the application defined in `backend/main.py`. When starting inside `backend/`,
Uvicorn imports that same application's module directly.

## Endpoints

| Route | Result |
| --- | --- |
| `GET /health` and `GET /api/health` | Service health and discovery provider names on the API route |
| `POST /api/verify` | Submit text and an optional filename. Returns job ID and bearer token |
| `GET /api/verify/{job_id}` | Job state and current stage |
| `GET /api/verify/{job_id}/claims` | Claim rows with references, evidence, verdicts and review reasons |
| `GET /api/verify/{job_id}/report` | Completed report with assessment details and claim rows |
| `GET /api/evidence/search` | Search selected providers with `q`, `providers` and `limit` |
| `GET /api/evidence/open-access` | Find an open-access location by DOI |
| `GET /api/evidence/core/works/{work_id}` | Retrieve a CORE work record |

Pass the returned bearer token when reading a new job. Private workspaces may configure
`VERIFICATION_ACCESS_KEY` and send the code in `X-Verification-Key` on submission.
The browser keeps job tokens in memory.

## Provider traffic and verification quotas

Metadata GET responses up to 256 KiB are cached in memory per process for five minutes
with a maximum of 128 entries. Cache keys distinguish request parameters and credentials.
Failed requests and no-store responses bypass the cache. Network errors and HTTP 429,
502, 503 and 504 can trigger up to two retries with jittered exponential backoff.
Retry-After delays above three seconds return control to the caller. Model submissions
and PDF streams use their own request paths.

Job admission uses an atomic database transaction shared by workers on the same database.
The limits are four active jobs and eight submissions per client address per hour.
To distinguish clients behind a reverse proxy, set `TRUSTED_PROXY_CIDRS` to the ingress
proxy addresses you control and start Uvicorn with `--no-proxy-headers` so VeriCite sees
the actual socket peer. The app walks X-Forwarded-For from right to left through trusted
hops. With the setting empty, the app uses the peer address. Separate service instances
with independent SQLite files have independent quotas.

## Testing

From the repository root, run `python -m unittest discover -s backend -v`. CI installs
`backend/requirements-ci.txt` for the default text/PyMuPDF path. Production requirements
also include Docling and optional embedding support.

## Run on Render

For an existing Python web service using the repository root, use these settings.

| Setting | Value |
|---|---|
| Root Directory | Leave blank |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `uvicorn main:app --no-proxy-headers --host 0.0.0.0 --port $PORT` |
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

To retrieve the full work record, call
`GET /api/evidence/core/works/{work_id}` with the `core_id` returned by search.
For example, `GET /api/evidence/core/works/267312` returns the CORE record,
including any full text, references, and repository metadata supplied by CORE.

### Citation verification providers

The verification job uses Crossref to validate DOIs and resolve bibliography entries.
OpenAlex can resolve a citation by title and provides open-access PDF locations and
abstracts. Semantic Scholar can resolve a citation when the earlier providers
cannot and supplies PDF links or abstracts for matching papers. When a PDF cannot
be read from the initial locations, the retriever can try Unpaywall and then
fall back to abstract evidence or mark the source unavailable.

Configure provider settings on the FastAPI server:

| Setting | Used for |
| --- | --- |
| `CROSSREF_MAILTO` | Optional Crossref contact email |
| `OPENALEX_API_KEY` | Authenticated OpenAlex requests |
| `SEMANTIC_SCHOLAR_API_KEY` | Optional authenticated Semantic Scholar requests |
| `UNPAYWALL_EMAIL` | Enables Unpaywall lookups for resolved DOIs |

Verification retrieves selectable PDF passages with PyMuPDF and ranks them with MiniLM embeddings and lexical signals. Set `EMBEDDING_MODEL=` for lightweight term ranking, which also provides the fallback when embeddings are unavailable.

### Reproduce the verification benchmark

Run `python backend/benchmark.py --api https://YOUR-BACKEND` from the repository root
to submit the sixteen public test statements. For an existing backend report, use
`python backend/benchmark.py --report report.json`. Each case checks the verdict,
citation identity and evidence trace. Missing, duplicate and unexpected results
fail the run. Exit status 0 means all sixteen cases passed, 1 means a mismatch,
and 2 indicates that the benchmark could not complete. This small benchmark
measures these sixteen cases only. A reviewer should inspect whether each passage
scientifically justifies the explanation.

### Persistent storage and verification checks

Set `VERICITE_DATABASE_URL` to a PostgreSQL connection string to share job data, access-token digests and quota counters across instances. All workers must use the same database. With this variable unset, SQLite uses `DB_PATH`; production SQLite requires a persistent volume. Selecting a new database starts a separate history. Existing SQLite jobs stay in the original database. The browser keeps bearer tokens in tab-scoped session storage.

Use trusted ingress CIDRs described above for proxy-based limits. Successful reference identities are cached for five minutes, scoped by DOI/title, authors and year. Each event loop permits three concurrent metadata GETs per provider host.

The API accepts extracted UTF-8 manuscript text in JSON with a TXT or Markdown filename and a two-million-byte text limit. PDF signature and size are checked in the browser before extraction. Production API responses carry CSP, HSTS and content-sniffing protection. Gemini receives task instructions and untrusted manuscript or passage data in separate message roles.
