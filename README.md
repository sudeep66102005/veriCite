# veriCite

**React + TypeScript + Tailwind CSS frontend** for INNOVEDGE Problem 03: CiteVerify — Scientific Claim and Citation Verification System.

The browser workspace extracts candidate claims and maps simple citations from research PDFs and plain text. It includes visual analytics, paper chat, source previews, manual source-PDF attachments, human review and report export. The standalone backend is separate from this browser workflow.

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

## Technology plan and current scope

| Layer | Technology | Role | Current scope |
|---|---|---|---|
| Frontend | React + TypeScript + Tailwind CSS | PDF upload UI, progress screen, claim cards, report | Implemented; typed components and Tailwind v4 Vite integration |
| Backend | Python + FastAPI | Uploads and extraction/retrieval/verification orchestration | Future integration; existing discovery backend untouched |
| PDF processing | PDF.js | Extract selectable PDF text in the browser | Implemented; scanned PDFs require OCR |
| Reference matching | Crossref API | Publication metadata and DOI matching | Future integration; local citation mapping and sample sources now |
| Source access | Unpaywall API + manual PDF upload | Locate accessible source papers | Manual local PDF attachment UI implemented; Unpaywall not called |
| AI verification | One hosted LLM API | Extract claims and compare with retrieved evidence | Sample fixtures only; no provider selected or key required |
| Data validation | Pydantic | Backend validation of verdict, explanation and evidence fields | Future backend; strict TypeScript plus runtime import validation now |
| Database | Supabase Postgres | Documents, claims, references, results, reviews | Not connected; browser localStorage now |
| File storage | Supabase Storage | Uploaded documents and retrieved source PDFs | Not connected; browser-memory File objects now |
| Testing | pytest + manually checked examples | Backend citation mapping and verdict/evidence accuracy | Future backend tests; current frontend uses Node test runner + TypeScript and browser checks |

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
- No research API, LLM, Supabase or backend calls are made. Google Fonts fetches font assets, with system font fallbacks available.

## Three-minute demonstration

1. Inspect the bundled sample; select the 30% overstatement and contradictory claim.
2. Filter by status, search for a phrase, and follow a citation issue to its claim.
3. Add a review note, flag the claim and inspect Review history. Reload to confirm persistence.
4. Open Document, select a PDF, run **Analyze PDF**, and inspect the extracted claims and references.
5. Attach a source PDF to a claim; explain that this is a local review attachment, not verified evidence.
6. Switch to text input and extract a custom paragraph with a reference list. Show its Unverified status.
7. Export JSON/CSV and restore the JSON report.

## Future API integration — no backend implementation in this change

Use the contracts in [`frontend/src/contracts.ts`](frontend/src/contracts.ts) when the backend is developed. They define future page locations, source passages, processing jobs, verified claims and review requests. UI/demo types live in `types.ts`; local demo operations live in `services.ts`.

| Proposed endpoint | Frontend purpose |
|---|---|
| `POST /api/documents` | Send multipart document; receive document ID and job ID |
| `GET /api/jobs/:id` | Real progress, partial completion and retryable errors |
| `GET /api/documents/:id/claims` | Claim text, location, references, verdict, explanation and original evidence |
| `POST /api/claims/:id/source-pdfs` | Attach a cited source PDF for retrieval/comparison |
| `POST /api/claims/:id/reviews` | Persist reviewer decision and note |
| `GET /api/documents/:id/report` | Export report with provenance and review history |

The browser analysis uses `runAnalysis`. Keep fixtures in an explicit demo mode and retain unverified/unavailable-source states. Do not point this UI at the existing search API and treat candidate publications as verified evidence.

### Planned backend flow

PyMuPDF extracts document text with page/bounding-box information → an LLM extracts structured claims → Crossref resolves references → Unpaywall or manual source PDFs provide permitted evidence → the LLM compares relevant source passages → Pydantic validates structured outputs → Supabase stores documents, sources, results and reviews.

Every verdict must reference an actual retrieved passage. Missing evidence should produce Unverified; ambiguous matches should require human review. Assess numeric claims, population, study scope and limitations. Evaluate against manually checked examples before reporting calibrated confidence.

### Credentials needed later

- **Crossref:** public metadata API; configure an application contact as appropriate. [Official documentation](https://www.crossref.org/documentation/retrieve-metadata/rest-api/).
- **Unpaywall:** contact email for API requests. [Official API documentation](https://unpaywall.org/products/api).
- **One hosted LLM:** choose one provider; keep its API key in the backend only.
- **Supabase:** project URL and client configuration when authentication is designed; backend privileged credentials remain server-only. Define Postgres and Storage row-level access policies before using real documents.

Never put LLM keys or Supabase service-role keys in React, `VITE_*` variables, source control or report exports. Pricing, quotas and available models should be confirmed at integration time.

## Code layout

```text
frontend/
  index.html
  vite.config.ts       Tailwind v4 Vite plugin
  tsconfig.json        Strict TypeScript configuration
  src/
    main.tsx           React entry
    App.tsx            Workspace and document workflow
    Evidence.tsx       Evidence, manual attachments and review
    Analytics.tsx      Metrics, charts, evidence reading and reference previews
    PaperChat.tsx      Rule-based contextual result exploration
    ui.tsx             Verdict badges, progress and downloads
    types.ts           Typed demo data models
    contracts.ts       Future backend contract types only
    engine.ts          Extraction, fixtures and report helpers
    services.ts        Local file validation, analysis and restoration
    pdf.ts             Local PDF text extraction
    engine.test.ts     Frontend regression tests
    styles.css         Tailwind import, theme and reusable utility compositions
backend/               Existing implementation, unchanged by this migration
```

## Validation and limits

The TypeScript/test/build commands above check citation mapping, honest unverified output, CSV escaping, persisted state validation, PDF header/size validation, cancellation, distinct PDF contents and unreadable PDFs. Manual browser checks cover the visible upload/progress workflow, report views and review interactions. Frontend tests do not establish scientific accuracy or live API availability. PyMuPDF, Pydantic, Supabase integration and pytest verification examples belong to the future backend work.
