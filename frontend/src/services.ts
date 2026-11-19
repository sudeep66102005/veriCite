import { extract, initialWorkspace } from './engine';
import { readPdfText } from './pdf';
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
export async function runAnalysis(input: { kind: 'pdf' | 'text'; title: string; text: string; file: File | null }, onStep: (step: number) => void, signal: AbortSignal): Promise<Workspace> {
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

  signal.throwIfAborted();
  onStep(file ? 2 : 1);
  const claims = extract(text);
  if (!claims.length) throw new Error('No candidate claims found. Add a sentence longer than 12 characters.');
  return {
    ...initialWorkspace(), claims,
    mode: file ? 'PDF · unverified' : 'Custom text · unverified',
    document: file?.name || input.title.trim() || 'Untitled document',
    requestedPdf: file ? fileMetadata(file) : null,
  };
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
    if (x.schemaVersion === 2 && typeof x.document === 'string' && ['Sample demo','Custom text · unverified','PDF · unverified','PDF workflow simulation'].includes(x.mode as string) && Array.isArray(x.attachments) && x.attachments.every(attachment) && (x.requestedPdf === null || metadata(x.requestedPdf))) return x as unknown as Workspace;
    // Preserve compatible review history from the previous JavaScript demo.
    if (typeof x.title === 'string') return { ...initialWorkspace(), document: typeof x.analyzedTitle === 'string' ? x.analyzedTitle : x.title, claims:x.claims, reviews:x.reviews as Record<string,Review>, history:x.history, mode:(x.mode === 'Sample demo' ? 'Sample demo' : 'Custom text · unverified') as Mode };
    return null;
  } catch { return null; }
}
export function restoreWorkspace(): Workspace {
  try { return decodeWorkspace(localStorage.getItem(STORAGE_KEY)) || decodeWorkspace(localStorage.getItem('vericite-v1')) || initialWorkspace(); }
  catch { return initialWorkspace(); }
}
