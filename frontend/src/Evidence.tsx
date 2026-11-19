import { useState } from 'react';
import { Check, ExternalLink, FileText, ShieldCheck, Upload, X } from 'lucide-react';
import { Badge } from './ui';
import type { Claim, Review, ReviewDecision, SourceAttachment } from './types';

interface Props {
  row: Claim;
  review?: Review;
  attachments: SourceAttachment[];
  availableFiles: Set<string>;
  onReview: (decision: ReviewDecision, note: string) => void;
  onAttach: (file: File) => Promise<void>;
  onOpen: (id: string) => void;
  onRemove: (id: string) => void;
}
export function Evidence({ row, review, attachments, availableFiles, onReview, onAttach, onOpen, onRemove }: Props) {
  const [note, setNote] = useState(review?.note || '');
  const [attaching, setAttaching] = useState(false);
  const safeUrl = row.source?.startsWith('https://doi.org/') ? row.source : null;
  return <aside className="panel lg:sticky lg:top-6" aria-label="Evidence inspector">
    <p className="eyebrow">EVIDENCE INSPECTOR</p><h2 className="mb-5 mt-2 font-display text-xl font-bold">Behind the claim</h2><Badge status={row.status}/>
    <blockquote className="my-5 text-base font-medium leading-7">{row.claim}</blockquote>
    <h3 className="section-label">SOURCE EVIDENCE</h3><div className="rounded-r-lg border-l-3 border-brand-500 bg-brand-50 p-4 text-sm leading-7 text-brand-900">{row.evidence}<p className="mt-3 text-xs text-brand-700">{row.section}</p></div>
    <h3 className="section-label">WHY THIS VERDICT?</h3><p className="text-sm leading-7 text-slate-500">{row.reason}</p>
    <div className="mt-4 flex items-center gap-2 rounded-lg bg-slate-50 p-3 text-sm text-slate-500"><ShieldCheck size={17}/>{row.confidence ? `${row.confidence} illustrative confidence` : 'Confidence unavailable'}</div>
    <h3 className="section-label">MATCHED REFERENCE</h3>{row.references.length ? row.references.map(r => <p key={r} className="mb-3 break-words text-sm leading-7 text-slate-500">{r}</p>) : <p className="text-sm text-slate-500">No matching reference found.</p>}
    {safeUrl && <a className="mt-3 inline-flex items-center gap-2 text-sm font-semibold text-brand-700" href={safeUrl} target="_blank" rel="noreferrer">Inspect original publication <ExternalLink size={15}/></a>}
    <section className="mt-6 border-t border-slate-100 pt-5"><h3 className="text-sm font-semibold">Manual source PDF</h3><p className="mt-2 text-sm leading-6 text-slate-500">Attach a cited paper for the review workflow. Files stay in memory; attaching does not verify the claim.</p>
      <label className="btn-secondary mt-3 w-full cursor-pointer"><Upload size={16}/>{attaching ? 'Checking file…' : 'Attach source PDF'}<input aria-label="Attach source PDF" type="file" accept=".pdf,application/pdf" className="sr-only" disabled={attaching} onChange={async e => { const file = e.target.files?.[0]; e.target.value = ''; if (!file) return; setAttaching(true); try { await onAttach(file); } finally { setAttaching(false); } }}/></label>
      <ul className="mt-3 space-y-2">{attachments.map(a => <li key={a.id} className="rounded-lg bg-slate-50 p-3"><div className="flex items-start gap-2"><FileText size={16} className="mt-1 text-brand-500"/><div className="min-w-0 flex-1"><p className="break-words text-sm font-medium">{a.name}</p><p className="mt-1 text-xs text-slate-500">{Math.ceil(a.size / 1024)} KB · {availableFiles.has(a.id) ? 'Local file available' : 'Metadata only — reattach to open'}</p></div><button aria-label={`Remove ${a.name}`} className="p-1 text-slate-400 hover:text-rose-600" onClick={() => onRemove(a.id)}><X size={16}/></button></div>{availableFiles.has(a.id) && <button className="mt-2 text-sm font-semibold text-brand-700" onClick={() => onOpen(a.id)}>Open local PDF</button>}</li>)}</ul>
    </section>
    <section className="mt-6 border-t border-slate-100 pt-5"><label className="label" htmlFor="review-note">Reviewer note</label><textarea id="review-note" rows={3} className="input resize-y" value={note} onChange={e => setNote(e.target.value)} placeholder="What needs a closer look?"/>
      <div className="mt-3 flex flex-wrap gap-2"><button className="btn" onClick={() => onReview('Reviewed', note)}><Check size={16}/>Mark reviewed</button><button className="btn-secondary" onClick={() => onReview('Needs follow-up', note)}>Flag for follow-up</button></div>
      {review && <p className="mt-3 text-xs leading-5 text-slate-500">{review.decision} · {new Date(review.at).toLocaleString()}</p>}
    </section>
  </aside>;
}
