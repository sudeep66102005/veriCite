import { Check, LoaderCircle, X } from 'lucide-react';
import type { PipelineStep, Verdict } from './types';

const colors: Record<Verdict, string> = {
  Supported: 'bg-emerald-50 text-emerald-700',
  'Partly supported': 'bg-amber-50 text-amber-700',
  Unsupported: 'bg-orange-50 text-orange-700',
  Contradictory: 'bg-rose-50 text-rose-700',
  'Possibly outdated': 'bg-violet-50 text-violet-700',
  Unverified: 'bg-slate-100 text-slate-600',
};
export function Badge({ status }: { status: Verdict }) {
  return <span className={`inline-block shrink-0 rounded-md px-2 py-1 text-xs font-semibold ${colors[status]}`}>{status}</span>;
}
export function Processing({ steps, step, pdf, onCancel }: { steps: PipelineStep[]; step: number; pdf: boolean; onCancel: () => void }) {
  return <section className="panel mt-6" aria-label="Processing progress" aria-busy="true">
    <div className="flex items-start justify-between gap-4"><div><p className="eyebrow">{pdf ? 'SIMULATED PDF WORKFLOW' : 'LOCAL TEXT PROCESSING'}</p><h2 className="mt-3 font-display text-xl font-bold">{pdf ? 'Preview the verification journey.' : 'Preparing your claim workspace.'}</h2></div><button className="btn-secondary" onClick={onCancel}><X size={16}/>Cancel</button></div>
    <p className="mt-3 text-sm leading-6 text-slate-500">{pdf ? 'Progress is simulated. Your PDF stays on this device; its text is not extracted. The final report uses clearly labelled sample claims.' : 'Claims are extracted with local heuristics. No research or AI services are called.'}</p>
    <div role="progressbar" aria-label="Processing progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(step / steps.length * 100)} className="my-7 h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-brand-500 transition-[width] motion-reduce:transition-none" style={{ width: `${step / steps.length * 100}%` }}/></div>
    <ol className="grid gap-5 md:grid-cols-2">{steps.map((s, i) => <li key={s.title} className={`flex gap-3 rounded-xl p-4 ${i === step ? 'bg-brand-50' : 'bg-slate-50'}`}><span className={`mt-0.5 ${i <= step ? 'text-brand-700' : 'text-slate-300'}`}>{i < step ? <Check size={20}/> : i === step ? <LoaderCircle size={20} className="animate-spin motion-reduce:animate-none"/> : <span className="block size-5 rounded-full border-2"/>}</span><div><h3 className="text-sm font-semibold">{s.title}</h3><p className="mt-1 text-sm leading-6 text-slate-500">{s.detail}</p></div></li>)}</ol>
  </section>;
}
export function download(name: string, content: string, type: string) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = document.createElement('a'); a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
