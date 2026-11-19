import { extract, initialWorkspace } from './engine';
import { readPdfText } from './pdf';
import { getJobClaims, getJobStatus, submitDocument, type VerificationRow } from './api';
import { verdicts, type Claim, type FileMetadata, type Mode, type PipelineStep, type Review, type SourceAttachment, type Workspace } from './types';

export const STORAGE_KEY = 'vericite-v2';
export const PDF_LIMIT = 10 * 1024 * 1024;
export function fileMetadata(file: File): FileMetadata { return { name: file.name, size: file.size, type: file.type }; }
export async function validatePdf(file: File): Promise<void> {
  if (!/\.pdf$/i.test(file.name)) throw new Error('Choose a PDF file.');
  if (file.size === 0) throw new Error('This PDF is empty. Choose another file.');
  if (file.size > PDF_LIMIT) throw new Error('Choose a PDF smaller than 10 MB.');
  const header = await file.slice(0, 5).text();
  if (header !== '%PDF-') throw new Error('The selected file does not have a PDF header.');
}
export const pdfSteps: PipelineStep[] = [
  { title: 'Check local file', detail: 'Validate the selected PDF header and size.' },
  { title: 'Read PDF text', detail: 'Extract selectable text from the PDF in your browser.' },
  { title: 'Extract claims and map citations', detail: 'Identify candidate claims and match simple bibliography entries.' },
];
export const textSteps: PipelineStep[] = [
  { title: 'Read document text', detail: 'Process the text locally in your browser.' },
  { title: 'Extract claims and map citations', detail: 'Identify candidate claims and match simple bibliography entries.' },
];
type DocumentInput = { kind: 'pdf' | 'text'; title: string; text: string; file: File | null };

async function prepareDocument(input: DocumentInput, onStep: (step: number) => void, signal: AbortSignal) {
  const file = input.kind === 'pdf' ? input.file : null;
  let text = input.text;
  signal.throwIfAborted();
  onStep(0);
  if (input.kind === 'pdf') {
    if (!file) throw new Error('Select a PDF before analyzing.');
    await validatePdf(file);
    signal.throwIfAborted();
    onStep(1);
    text = await readPdfText(file, signal);
  } else if (!text.trim()) throw new Error('Paste academic text or import a TXT/Markdown file.');

  return { text, file, title: file?.name || input.title.trim() || 'Untitled document' };
}

export async function runAnalysis(input: DocumentInput, onStep: (step: number) => void, signal: AbortSignal): Promise<Workspace> {
  const { text, file, title } = await prepareDocument(input, onStep, signal);
  signal.throwIfAborted();
  onStep(file ? 2 : 1);
  const claims = extract(text);
  if (!claims.length) throw new Error('No candidate claims found. Add a sentence longer than 12 characters.');
  return {
    ...initialWorkspace(), claims,
    mode: file ? 'PDF · unverified' : 'Custom text · unverified',
    document: title,
    requestedPdf: file ? fileMetadata(file) : null,
  };
}
const verificationSteps: PipelineStep[] = [
  { title: 'Submit document text', detail: 'Send the manuscript text to the verification service.' },
  { title: 'Read manuscript', detail: 'Identify manuscript sections and bibliography.' },
  { title: 'Extract cited claims', detail: 'Find claims and map them to cited references.' },
  { title: 'Resolve references', detail: 'Match citations to publication records.' },
  { title: 'Retrieve passages', detail: 'Find available passages from cited sources.' },
  { title: 'Assess claims', detail: 'Compare claims with the available passages.' },
];
export const pdfVerificationSteps = [...pdfSteps.slice(0, 2), ...verificationSteps];
export const textVerificationSteps = [...textSteps.slice(0, 1), ...verificationSteps];

const semanticVerdicts = {
  SUPPORTED: 'Supported',
  PARTLY_SUPPORTED: 'Partly supported',
  UNSUPPORTED: 'Unsupported',
  CONTRADICTORY: 'Contradictory',
} as const;

function toClaim(row: VerificationRow): Claim {
  const { assessment, evidence } = row;
  const verdict = assessment?.assessment_status === 'assessed' && row.mapping === 'mapped' &&
    evidence.length && assessment.semantic_verdict ? semanticVerdicts[assessment.semantic_verdict] : 'Unverified';
  return {
    id: row.id,
    claim: row.text,
    markers: row.marker ? [row.marker] : [],
    references: row.reference ? [row.reference] : [],
    status: verdict,
    confidence: null,
    evidence: evidence.map(p => p.verbatim_text).join('\n\n') || 'No source passage is available for this assessment.',
    section: evidence.map(p => [p.section, p.page !== null ? `Page ${p.page}` : null].filter(Boolean).join(' · ')).filter(Boolean).join(', ') || 'Not available',
    reason: row.extraction_error ? `Original cited text retained for review. ${row.extraction_error}` : row.mapping === 'ambiguous' ? 'The citation mapping requires human review.' :
      assessment?.explanation || 'The service could not assess this claim against a cited source.',
    flags: [...(row.extraction_error ? ['Extraction incomplete'] : []), ...(assessment?.issue_flags || []), ...(row.mapping && row.mapping !== 'mapped' ? [`Citation mapping: ${row.mapping}`] : [])],
    source: row.doi ? `https://doi.org/${encodeURI(row.doi)}` : null,
  };
}

export async function runVerification(input: DocumentInput, onStep: (step: number) => void, cancellation: AbortSignal) {
  const { text, file, title } = await prepareDocument(input, onStep, cancellation);
  const signal = AbortSignal.any([cancellation, AbortSignal.timeout(10 * 60_000)]);
  const offset = file ? 2 : 1;
  // Keep bibliography headings visible to the server's paragraph parser.
  const manuscript = text.replace(/^([ \t]*(?:References|Bibliography)[ \t]*:?[ \t]*)$/gim, '\n\n$1\n\n');
  onStep(offset);
  const { job_id } = await submitDocument(manuscript, `${title}.txt`, signal);
  let job = await getJobStatus(job_id, signal);
  while (job.job_state === 'queued' || job.job_state === 'running') {
    onStep(offset + (job.current_stage ?? 0));
    await new Promise(resolve => setTimeout(resolve, 1800));
    signal.throwIfAborted();
    job = await getJobStatus(job_id, signal);
  }
  if (job.job_state !== 'completed') throw new Error('The verification job failed on the server. Try again or check the backend logs.');
  const { rows } = await getJobClaims(job_id, signal);
  if (!Array.isArray(rows)) throw new Error('The verification server needs the latest backend deployment.');
  const issues = job.report?.stage_errors.length ?? 0;
  if (!rows.length && job.report?.stage_errors.some(issue => issue.includes('no ref_ids') || issue.includes('unmatched citation marker'))) throw new Error('Citation markers were found, but no claims could be linked. Check that the extracted text includes readable bibliography entries.');
  if (!rows.length) throw new Error('The verifier found no cited claims. Check that the document text contains readable citations and a References section.');
  const workspace: Workspace = {
    ...initialWorkspace(),
    claims: rows.map(toClaim),
    mode: 'API verification',
    document: title,
    requestedPdf: file ? fileMetadata(file) : null,
  };
  return { workspace, issues };
}

const object = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null;
const strings = (v: unknown): v is string[] => Array.isArray(v) && v.every(x => typeof x === 'string');
const claim = (v: unknown): v is Claim => object(v) && typeof v.id === 'string' && typeof v.claim === 'string' && strings(v.markers) && strings(v.references) && verdicts.includes(v.status as Claim['status']) && [null,'High','Medium','Low'].includes(v.confidence as string|null) && typeof v.evidence === 'string' && typeof v.section === 'string' && typeof v.reason === 'string' && strings(v.flags) && (v.source === null || typeof v.source === 'string');
const review = (v: unknown): v is Review => object(v) && typeof v.claimId === 'string' && ['Reviewed','Needs follow-up'].includes(v.decision as string) && typeof v.note === 'string' && typeof v.at === 'string';
const metadata = (v: unknown): v is FileMetadata => object(v) && typeof v.name === 'string' && typeof v.size === 'number' && typeof v.type === 'string';
const attachment = (v: unknown): v is SourceAttachment => metadata(v) && object(v) && typeof v.id === 'string' && typeof v.claimId === 'string' && typeof v.addedAt === 'string';
export function decodeWorkspace(raw: string | null): Workspace | null {
  try {
    const x: unknown = JSON.parse(raw || 'null');
    if (!object(x) || !Array.isArray(x.claims) || !x.claims.every(claim) || !object(x.reviews) || !Object.values(x.reviews).every(review) || !Array.isArray(x.history) || !x.history.every(review)) return null;
    if (x.schemaVersion === 2 && typeof x.document === 'string' && ['API verification','Sample demo','Custom text · unverified','PDF · unverified','PDF workflow simulation'].includes(x.mode as string) && Array.isArray(x.attachments) && x.attachments.every(attachment) && (x.requestedPdf === null || metadata(x.requestedPdf))) return x as unknown as Workspace;
    // Preserve compatible review history from the previous JavaScript demo.
    if (typeof x.title === 'string') return { ...initialWorkspace(), document: typeof x.analyzedTitle === 'string' ? x.analyzedTitle : x.title, claims:x.claims, reviews:x.reviews as Record<string,Review>, history:x.history, mode:(x.mode === 'Sample demo' ? 'Sample demo' : 'Custom text · unverified') as Mode };
    return null;
  } catch { return null; }
}
export function restoreWorkspace(): Workspace {
  try { return decodeWorkspace(localStorage.getItem(STORAGE_KEY)) || decodeWorkspace(localStorage.getItem('vericite-v1')) || initialWorkspace(); }
  catch { return initialWorkspace(); }
}
