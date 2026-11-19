# CiteVerify backend

This starter directory provides the five-stage package layout, API configuration template, dependencies, and a working FastAPI health endpoint. The verification pipeline and external clients are pending implementation.

## Start locally

Run from this directory with Python 3.11 and a virtual environment.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --env-file .env --reload
```

Check the running process with `curl http://127.0.0.1:8000/health`. This endpoint can run without credentials. Fill in provider credentials before implementing live jobs. Crossref uses a contact email.

## Package responsibilities and data flow

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

The health endpoint is the only implemented route. Cache resolution and parsing per unique source. Keep manuscript spans and source spans separately. Preserve source coverage and lookup failures independently of semantic verdicts. Attach currency and retraction warnings separately. Validate model-selected passage IDs before copying quotes and page locations into reports.
