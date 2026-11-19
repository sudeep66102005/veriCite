# veriCite

**React + TypeScript + Tailwind CSS frontend** for INNOVEDGE Problem 03: CiteVerify — Scientific Claim and Citation Verification System.

The browser workspace extracts candidate claims and maps simple citations from research PDFs and plain text. It includes visual analytics, paper chat, source previews, manual source-PDF attachments, human review and report export. The workspace can send extracted document text to the verification backend.

## Run

Use Node.js 22.13+ (Node 24 recommended).

```bash
cd frontend
npm ci
npm run dev
```

Open the Vite URL printed in your terminal.

```bash
npm run typecheck
npm test
npm run build
npm run preview
```

`build` runs strict TypeScript checks before Vite. Deploy `frontend/dist` on a static host. For Vercel, set the root directory to `frontend`, build command to `npm run build`, and output directory to `dist`. No keys or environment variables are required for browser-local analysis.

## Verification backend

The React workspace reads selectable PDF text with PDF.js. When connected to FastAPI it
submits the manuscript, polls a verification job, and displays a result for each citation.
The backend stores jobs and review evidence in SQLite. It resolves publications with Crossref,
OpenAlex and Semantic Scholar and can use Unpaywall to locate full text. The configured
Gemini model compares retrieved passages. Local extraction and the sample remain available
without backend credentials.

## Eight frontend feature groups

1. **Document input:** select or drop a PDF up to 10 MB, inspect the selected file through a local browser URL, remove it, or import TXT/Markdown up to 1 MB. Paste/edit text and document titles.
2. **Processing progress:** local PDF extraction with accessible progress, cancellation and error feedback. Cancellation preserves the previous report.
3. **Claim cards and verdict dashboard:** six sample verdicts, summary counts, selected-claim state, responsive layout and empty states. PDFs and custom text produce unverified candidate claims.
4. **Citation mapping and issues:** simple `[1]` and `(Author, Year)` mappings under References/Bibliography; missing/unmatched reference flags and illustrative scope/number/freshness issues.
5. **Evidence and manual sources:** evidence paraphrase, reason, illustrative uncertainty, matched reference and safe DOI link; attach/remove source PDFs per claim and open them while this session retains their bytes.
6. **Search and filters:** search claims/references, filter by verdict, clear empty results, and navigate from a reference issue to its claim.
7. **Human review:** reviewer notes, reviewed/follow-up decisions and timestamped history. Compatible previous demo history is migrated locally. Decisions never automatically change scientific verdicts.
8. **Reports:** JSON export with reviews, provenance, analysis mode and attachment metadata; CSV export of all claims; restore a validated JSON report. Draft title edits do not rename a completed report.

## Analyze a PDF

Open **Document**, select a text-based PDF up to 10 MB and choose **Analyze PDF**. PDF.js reads the selected file in your browser and the report uses its filename, candidate claims and matched bibliography entries. The app reports unreadable or textless files as errors. Use OCR to make scanned documents searchable first.

**Paste or import text** uses the same sentence and citation heuristics. PDF layout and complex citation formats can affect how text, claims and references are recognized. Candidate claims remain **Unverified** pending evidence assessment. Use **Load sample** to see the illustrative report.

Sample evidence is authored paraphrase, not retrieved quotations; sample confidence is illustrative, not a calibrated probability. A DOI link alone does not prove a claim. Old publication dates alone do not invalidate findings.

## Persistence and privacy

- Reports, review notes and attachment **metadata** use localStorage (`vericite-v2`). Compatible v1 reports can migrate without deleting old storage.
- PDF bytes and object URLs live only in browser memory and are released when removed/replaced or the app closes. After reload, source attachments explicitly show “Metadata only — reattach to open.”
- JSON exports contain claims, notes, filenames and other report metadata, but not PDF bytes. Keep this in mind when sharing a report.
- Loading a sample or completing a new analysis replaces the current report and its review history. Export JSON first if you want to keep it; it can be restored later.
- When backend verification is enabled, manuscript text is sent to the backend and claim excerpts may be processed by its configured model. Google Fonts fetches font assets, with system font fallbacks available.

## Three-minute demonstration

1. Inspect the bundled sample; select the 30% overstatement and contradictory claim.
2. Filter by status, search for a phrase, and follow a citation issue to its claim.
3. Add a review note, flag the claim and inspect Review history. Reload to confirm persistence.
4. Open Document, select a PDF, run **Analyze PDF**, and inspect the extracted claims and references.
5. Attach a source PDF to a claim; explain that this is a local review attachment, not verified evidence.
6. Switch to text input and extract a custom paragraph with a reference list. Show its Unverified status.
7. Export JSON/CSV and restore the JSON report.

## Verify a manuscript

Run the backend as described in [the backend guide](backend/README.md).
Set `VITE_API_URL` when building the frontend for a separate deployment.
Submit text with `POST /api/verify`. Keep the returned access token in memory and
send it as an Authorization bearer token for job status, claims and report requests.
Private workspaces can set `VERIFICATION_ACCESS_KEY` on the backend and enter that code under Private workspace access in the document tab.
Previously created jobs retain their existing private-link access.

Uncited statements and unmatched or ambiguous citations remain available for review.
A verdict requires a passage from the matched publication. When a newer citing abstract
explicitly revises the same finding, the report can show a **Possibly outdated** verdict
with the newer publication and its passage. Coverage varies with open-access availability.

The server accepts four active verification jobs across workers sharing its SQLite database
and eight submissions per direct peer address per hour. Each job has a nine-minute deadline,
up to eight compound-claim extraction requests and forty claim–reference assessments.
Extra pairs stay visible for review. Behind a reverse proxy, clients may share an allowance.

Run backend checks with `python -m unittest discover -s backend` and frontend checks with
`npm test && npm run build` from `frontend/`. The acceptance manuscript and answer key are
in [the verification benchmark](backend/fixtures/verification-benchmark.md).

## Connect the deployed frontend

Set `VITE_API_URL` to the public Render backend origin in Vercel and rebuild the
frontend. The Render backend allows cross-origin requests from
`https://veri-cite-two.vercel.app`. Local Vite development uses its existing
proxy to port 8000 when no API URL is configured. Production builds without an
API URL use local extraction. Verified results are shown per claim and cited source.
