import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, BookOpen, ChartNoAxesColumnIncreasing, MessageSquare, Check, ChevronRight, Download, ExternalLink, FileText, FlaskConical, History, LayoutDashboard, RotateCcw, Search, ShieldCheck, Upload, X, type LucideIcon } from 'lucide-react';
import { csv, initialWorkspace, report, sampleText, statuses } from './engine';
import { decodeWorkspace, fileMetadata, pdfSteps, pdfVerificationSteps, restoreWorkspace, runAnalysis, runVerification, STORAGE_KEY, textSteps, textVerificationSteps, validatePdf } from './services';
import { verificationEnabled } from './api';
import { Badge, download, Processing } from './ui';
import { Evidence } from './Evidence';
import { Analytics } from './Analytics';
import { PaperChat } from './PaperChat';
import type { ReviewDecision, Workspace } from './types';

type Tab = 'Visual Analytics' | 'Paper chat' | 'Reports' | 'Overview' | 'Document' | 'References' | 'Review history';
const navigation: { icon: LucideIcon; label: Tab }[] = [
  { icon: ChartNoAxesColumnIncreasing, label: 'Visual Analytics' },
  { icon: LayoutDashboard, label: 'Overview' }, { icon: FileText, label: 'Document' },
  { icon: BookOpen, label: 'References' }, { icon: FileText, label: 'Reports' }, { icon: MessageSquare, label: 'Paper chat' }, { icon: History, label: 'Review history' },
];

export default function App() {
  const [state, setState] = useState<Workspace>(restoreWorkspace);
  const [tab, setTab] = useState<Tab>('Visual Analytics');
  const [selected, setSelected] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('All verdicts');
  const [message, setMessage] = useState('');
  const [kind, setKind] = useState<'pdf' | 'text'>('pdf');
  const [title, setTitle] = useState('My research document');
  const [text, setText] = useState(sampleText);
  const [pdf, setPdf] = useState<File | null>(null);
  const [pdfUrl, setPdfUrl] = useState('');
  const [reading, setReading] = useState(false);
  const [step, setStep] = useState<number | null>(null);
  const [sourceUrls, setSourceUrls] = useState<Record<string, string>>({});
  const fileUrls = useRef<Record<string, string>>({});
  const controller = useRef<AbortController | null>(null);
  const selectionVersion = useRef(0);

  useEffect(() => { try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); } catch { setMessage('Browser storage unavailable. Export a report to keep your work.'); } }, [state]);
  useEffect(() => { if (!pdf) { setPdfUrl(''); return; } const url = URL.createObjectURL(pdf); setPdfUrl(url); return () => URL.revokeObjectURL(url); }, [pdf]);
  useEffect(() => () => { controller.current?.abort(); Object.values(fileUrls.current).forEach(URL.revokeObjectURL); }, []);
  const visible = state.claims.filter(r => (filter === 'All verdicts' || r.status === filter) && `${r.claim} ${r.references.join(' ')}`.toLowerCase().includes(query.toLowerCase()));
  const row = visible.find(r => r.id === selected) || visible[0];
  const reviewed = state.claims.filter(r => state.reviews[r.id]).length;
  const busy = step !== null;

  function clearSources() { Object.values(fileUrls.current).forEach(URL.revokeObjectURL); fileUrls.current = {}; setSourceUrls({}); }
  function applyResult(next: Workspace) { clearSources(); setState(next); setSelected(null); setQuery(''); setFilter('All verdicts'); setTab('Overview'); }
  function loadSample() { controller.current?.abort(); controller.current = null; setStep(null); applyResult(initialWorkspace()); setMessage('Sample loaded. Claims and evidence are illustrative.'); }
  async function selectFile(file: File | undefined) {
    if (!file) return;
    const version = ++selectionVersion.current; setReading(true);
    try {
      if (kind === 'pdf') { await validatePdf(file); if (version !== selectionVersion.current) return; setPdf(file); setMessage('PDF selected locally. Select Analyze PDF to extract its claims.'); }
      else {
        if (!/\.(txt|md)$/i.test(file.name) || file.size > 1024 * 1024) throw new Error('Choose a TXT/Markdown file up to 1 MB.');
        const content = await file.text(); if (version !== selectionVersion.current) return; setText(content); setTitle(file.name); setMessage('Text loaded.');
      }
    } catch (error) {
      if (version !== selectionVersion.current) return;
      if (kind === 'pdf') setPdf(null);
      setMessage(error instanceof Error ? error.message : 'Could not read the file.');
    }
    finally { if (version === selectionVersion.current) setReading(false); }
  }
  async function processDocument() {
    const abort = new AbortController(); controller.current = abort; setStep(0); setMessage('');
    try {
      const input = { kind, title, text, file: pdf };
      const { workspace: next, issues } = verificationEnabled
        ? await runVerification(input, setStep, abort.signal)
        : { workspace: await runAnalysis(input, setStep, abort.signal), issues: 0 };
      if (abort.signal.aborted) return;
      applyResult(next);
      const incomplete = next.claims.filter(claim => claim.flags.includes('Extraction incomplete')).length;
      if (incomplete) {
        setMessage(`Gemini extraction was unavailable for ${incomplete} claim–citation results. Their original cited text is in the report, marked Unverified.`);
        return;
      }
      setMessage(verificationEnabled ? `Verification returned ${next.claims.length} claim–citation results for ${next.document}.${issues ? " Some pipeline stages reported issues. Review unverified results." : ""}` : `Extracted ${next.claims.length} candidate claims locally. All remain unverified.`);
    } catch (error) {
      if (!abort.signal.aborted) setMessage(error instanceof Error ? error.message : 'Processing failed. Please retry.');
    } finally { if (controller.current === abort) { controller.current = null; setStep(null); } }
  }
  function cancelProcess() { controller.current?.abort(); controller.current = null; setStep(null); setMessage('Processing cancelled. Your previous report is unchanged.'); }
  function review(decision: ReviewDecision, note: string) {
    if (!row) return;
    const entry = { claimId: row.id, decision, note, at: new Date().toISOString() };
    setState(s => ({ ...s, reviews: { ...s.reviews, [row.id]: entry }, history: [entry, ...s.history] }));
    setMessage('Review saved in this browser.');
  }
  async function attach(file: File) {
    if (!row) return; const claimId = row.id;
    try {
      await validatePdf(file);
      const id = crypto.randomUUID(), url = URL.createObjectURL(file);
      fileUrls.current[id] = url; setSourceUrls({ ...fileUrls.current });
      setState(s => ({ ...s, attachments: [...s.attachments, { ...fileMetadata(file), id, claimId, addedAt: new Date().toISOString() }] }));
      setMessage('Source attached locally. Its contents have not been parsed and the verdict is unchanged.');
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Could not attach the PDF.'); }
  }
  function removeAttachment(id: string) { URL.revokeObjectURL(fileUrls.current[id]); delete fileUrls.current[id]; setSourceUrls({ ...fileUrls.current }); setState(s => ({ ...s, attachments: s.attachments.filter(a => a.id !== id) })); }
  async function importReport(file: File | undefined) {
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) { setMessage('Choose a JSON report smaller than 2 MB.'); return; }
    try { const restored = decodeWorkspace(await file.text()); if (!restored) throw new Error('This file is not a compatible veriCite report.'); applyResult(restored); setMessage('Report restored. PDF attachments contain metadata only; reattach files to open them.'); }
    catch (error) { setMessage(error instanceof Error ? error.message : 'Could not import this report.'); }
  }
  const exportJson = () => download('vericite-report.json', JSON.stringify(report(state), null, 2), 'application/json');

  return <div className="min-h-screen">
    <nav className="fixed inset-y-0 left-0 z-20 flex w-16 flex-col border-r border-slate-200 bg-white px-2 py-6 md:w-56 md:px-4" aria-label="Workspace navigation">
      <button className="mx-auto mb-10 flex items-center gap-2 font-display text-2xl font-extrabold tracking-tight text-brand-900 md:mx-2" aria-label="VeriSite home" onClick={() => setTab('Overview')}><span className="rounded-xl bg-brand-700 p-2 text-white"><ShieldCheck size={23}/></span><span className="hidden md:inline">Veri<span className="text-brand-500">Site</span></span></button>
      <p className="mb-4 hidden px-3 text-xs font-bold tracking-widest text-slate-400 md:block">RESEARCH WORKSPACE</p>
      {navigation.map(({ icon: Icon, label }) => <button key={label} aria-label={label} aria-current={tab === label ? 'page' : undefined} className={`my-1 flex items-center justify-center gap-3 rounded-lg px-3 py-3.5 text-sm font-medium md:justify-start ${tab === label ? 'bg-brand-50 text-brand-700' : 'text-slate-500 hover:bg-slate-50'}`} onClick={() => setTab(label)}><Icon size={20}/><span className="hidden md:inline">{label}</span>{label === 'Overview' && <span className="ml-auto hidden rounded bg-brand-100 px-1.5 py-0.5 text-xs md:inline">{state.claims.length}</span>}</button>)}
      <div className="mt-auto hidden rounded-xl border border-brand-100 bg-brand-50 p-4 text-brand-700 md:block"><FlaskConical size={22}/><p className="mt-3 text-sm font-semibold">Built for academic trust</p><p className="mt-2 text-sm leading-6 text-slate-500">Every finding is a starting point for human review.</p><span className="mt-3 inline-block rounded border border-brand-100 px-2 py-1 text-xs tracking-wider">LOCAL WORKSPACE</span></div>
      <p className="mt-6 hidden border-t border-slate-100 pt-4 text-xs text-slate-400 md:block">Local browser workspace</p>
    </nav>
    <main className="ml-16 min-w-0 md:ml-56">
      <header className="flex min-h-20 items-center justify-between gap-3 border-b border-slate-200 bg-white px-4 sm:px-8"><p className="flex items-center gap-2 text-sm text-slate-500"><span className="hidden sm:inline">Workspace</span><ChevronRight size={15}/>{tab}</p><button className="btn-secondary" onClick={exportJson}><Download size={16}/>Export report</button></header>
      <div className="mx-auto max-w-[1440px] px-4 py-7 sm:px-8 sm:py-10">
        <p className="eyebrow">READ. QUESTION. VERIFY.</p><h1 className="mt-3 font-display text-3xl font-extrabold leading-tight tracking-tight sm:text-4xl">{tab === 'Visual Analytics' ? 'Visual Analytics' : 'Confidence starts with evidence.'}</h1><p className="mb-6 mt-3 max-w-3xl text-base leading-7 text-slate-500">Trace every claim back to its source. See what holds up—and what needs a closer look.</p>
        <div className="flex flex-wrap items-start gap-3 rounded-xl border border-brand-100 bg-brand-50 p-4 text-sm leading-6 text-brand-700"><FlaskConical size={20} className="mt-0.5"/><p className="min-w-0 flex-1"><strong>{state.mode}.</strong> {state.mode === 'PDF workflow simulation' ? 'PDF contents were not parsed. This report uses illustrative sample claims and evidence.' : state.mode === 'Sample demo' ? 'Sample evidence is illustrative.' : state.mode === 'API verification' ? 'Verdicts apply to individual cited sources. Review the source passages before relying on a result.' : 'Candidate claims were extracted locally and await evidence verification.'}</p><button className="font-semibold underline underline-offset-4" onClick={loadSample}>Load sample</button></div>
        {state.requestedPdf && <p className="mt-3 break-words text-sm text-slate-500">{state.mode === 'PDF workflow simulation' ? 'Selected for simulation' : 'Analyzed PDF'} · {state.requestedPdf.name} · {Math.ceil(state.requestedPdf.size / 1024)} KB</p>}
        {message && <div role="status" className="mt-4 flex items-start justify-between gap-3 rounded-xl bg-amber-50 p-4 text-sm leading-6 text-amber-900"><span>{message}</span><button aria-label="Dismiss message" onClick={() => setMessage('')}><X size={18}/></button></div>}
        {busy ? <Processing steps={kind === 'pdf' ? (verificationEnabled ? pdfVerificationSteps : pdfSteps) : (verificationEnabled ? textVerificationSteps : textSteps)} verify={verificationEnabled} step={step!} pdf={kind === 'pdf'} onCancel={cancelProcess}/> : tab === 'Visual Analytics' ? <Analytics state={state} upload={() => setTab('Document')} inspect={id=>{setSelected(id);setQuery('');setFilter('All verdicts');setTab('Overview');}}/> : tab === 'Paper chat' ? <PaperChat key={state.document + state.mode + state.claims.map(c=>c.claim).join('')} state={state}/> : tab === 'Reports' ? <section className="panel mt-6"><h2 className="text-xl font-bold">Verification report</h2><p className="my-4 text-sm text-slate-500">{state.document}</p><div className="flex flex-wrap gap-3"><button className="btn" onClick={exportJson}>Download JSON</button><button className="btn-secondary" onClick={()=>download('vericite-claims.csv',csv(state.claims),'text/csv')}>Download CSV</button><button className="btn-secondary" onClick={()=>setTab('References')}>References</button><button className="btn-secondary" onClick={()=>setTab('Review history')}>Review history</button></div></section> : tab === 'Document' ? <section className="panel mt-6">
          <div className="flex flex-wrap items-start justify-between gap-4"><div><h2 className="font-display text-xl font-bold">Your research, ready for review.</h2><p className="mt-2 text-sm leading-6 text-slate-500">Extract candidate claims from a research PDF or plain text.</p></div><label className="btn-secondary cursor-pointer"><RotateCcw size={16}/>Restore JSON report<input className="sr-only" aria-label="Restore JSON report" type="file" accept=".json" onChange={e => { void importReport(e.target.files?.[0]); e.target.value = ''; }}/></label></div>
          <div className="my-6 inline-flex flex-wrap gap-1 rounded-xl bg-slate-100 p-1" role="group" aria-label="Document input type">{(['pdf', 'text'] as const).map(k => <button aria-pressed={kind === k} disabled={reading} key={k} className={`rounded-lg px-4 py-2.5 text-sm font-semibold ${kind === k ? 'bg-white text-brand-700 shadow-sm' : 'text-slate-500'}`} onClick={() => setKind(k)}>{k === 'pdf' ? 'Research PDF' : 'Paste or import text'}</button>)}</div>
          <div onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); if (!reading) void selectFile(e.dataTransfer.files[0]); }} className="rounded-xl border-2 border-dashed border-brand-100 bg-brand-50/40 p-6 text-center sm:p-9"><Upload className="mx-auto text-brand-500" size={28}/><h3 className="mt-4 font-semibold">{kind === 'pdf' ? 'Drop your research PDF here' : 'Drop a TXT or Markdown file here'}</h3><p className="mb-4 mt-2 text-sm text-slate-500">{kind === 'pdf' ? 'PDF up to 10 MB' : 'TXT or Markdown up to 1 MB'}</p><label className="btn cursor-pointer">{reading ? 'Reading file…' : 'Choose document'}<input disabled={reading} aria-label="Choose document" className="sr-only" type="file" accept={kind === 'pdf' ? '.pdf,application/pdf' : '.txt,.md'} onChange={e => { void selectFile(e.target.files?.[0]); e.target.value = ''; }}/></label></div>
          {kind === 'pdf' ? <><div className="mt-5 rounded-xl border border-amber-100 bg-amber-50 p-4 text-sm leading-7 text-amber-900">{verificationEnabled ? 'The app sends selectable PDF text to the verification backend.' : 'The app extracts candidate claims locally.'} Scanned PDFs require OCR first.</div>{pdf && <div className="my-5 flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 p-4"><FileText className="text-brand-500"/><div className="min-w-0 flex-1"><p className="break-words text-sm font-semibold">{pdf.name}</p><p className="mt-1 text-xs text-slate-500">{Math.ceil(pdf.size / 1024)} KB · locally selected</p></div>{pdfUrl && <a className="btn-secondary" href={pdfUrl} target="_blank" rel="noreferrer">Open PDF <ExternalLink size={14}/></a>}<button className="btn-secondary" onClick={() => setPdf(null)}>Remove</button></div>}<button disabled={!pdf || reading} className="btn mt-5" onClick={() => void processDocument()}><FlaskConical size={17}/>Analyze PDF</button></> : <div className="mt-6"><label className="label" htmlFor="document-title">Document name</label><input id="document-title" className="input" value={title} onChange={e => setTitle(e.target.value)}/><label className="label mt-5" htmlFor="document-text">Document text</label><textarea id="document-text" className="input resize-y" rows={13} value={text} onChange={e => setText(e.target.value)}/><p className="mt-2 text-sm leading-6 text-slate-500">Include a References heading and simple [1] or (Author, Year) citations. {verificationEnabled ? 'The text is sent to the verification backend.' : 'Candidate claims remain unverified.'}</p><button disabled={reading} className="btn mt-5" onClick={() => void processDocument()}>{verificationEnabled ? 'Verify text' : 'Extract claims'}</button></div>}
        </section> : tab === 'References' ? <section className="panel mt-6"><h2 className="font-display text-xl font-bold">Follow the source trail</h2><p className="my-3 text-sm leading-7 text-slate-500">Browse the bibliography entries linked to the results.</p>{[...new Set(state.claims.flatMap(r => r.references))].map((ref, i) => <article key={ref} className="flex gap-4 border-t border-slate-100 py-6"><BookOpen className="mt-1 text-brand-500"/><div className="min-w-0"><h3 className="font-semibold">Reference {i + 1}</h3><p className="my-2 break-words text-sm leading-7 text-slate-500">{ref}</p><p className="text-xs text-slate-400">Linked to {state.claims.filter(r => r.references.includes(ref)).length} claims</p></div></article>)}{!state.claims.some(r => r.references.length) && <p className="py-8 text-sm text-slate-500">No references mapped. Add a References section to your text document.</p>}<h3 className="mb-4 mt-5 font-semibold">Citation issues</h3>{state.claims.filter(r => r.flags.length).map(r => <button key={r.id} className="my-2 flex w-full items-start gap-3 rounded-lg bg-amber-50 p-4 text-left text-sm text-amber-800" onClick={() => { setSelected(r.id); setFilter('All verdicts'); setQuery(''); setTab('Overview'); }}><AlertTriangle size={18} className="mt-1"/><span>{r.flags.join(' · ')}<span className="mt-2 block text-sm leading-6 text-slate-500">{r.claim}</span></span></button>)}</section> : tab === 'Review history' ? <section className="panel mt-6"><h2 className="font-display text-xl font-bold">A transparent review trail</h2><p className="my-3 text-sm text-slate-500">{state.history.length} decisions saved on this device.</p>{!state.history.length && <div className="py-12 text-center text-slate-500"><History className="mx-auto mb-4"/><h3 className="font-semibold">No reviews yet</h3><p className="mt-2 text-sm">Select a claim, add a note, and mark it reviewed or flag it.</p></div>}{state.history.map((h, i) => <article key={`${h.at}-${i}`} className="flex gap-4 border-t border-slate-100 py-6"><Check size={20} className="mt-1 text-brand-500"/><div><h3 className="font-semibold">{h.decision}</h3><p className="my-2 text-sm leading-7 text-slate-500">{state.claims.find(r => r.id === h.claimId)?.claim}</p>{h.note && <blockquote className="my-3 border-l-3 border-brand-100 bg-brand-50 p-3 text-sm leading-6">{h.note}</blockquote>}<p className="text-xs text-slate-400">{new Date(h.at).toLocaleString()}</p></div></article>)}</section> : <>
          <section className="my-6 grid grid-cols-2 gap-y-6 rounded-2xl border border-slate-200 bg-white py-6 lg:grid-cols-4" aria-label="Report summary">{[
            { value: state.claims.length, label: 'Claims extracted', hint: state.mode === 'API verification' ? 'Claim–citation results' : 'Candidate claims' },
            { value: state.claims.filter(r => r.status === 'Supported').length, label: 'Supported', hint: 'Supported by available evidence' },
            { value: state.claims.filter(r => r.status !== 'Supported').length, label: 'Need attention', hint: 'Check evidence & context' },
            { value: `${reviewed}/${state.claims.length}`, label: 'Human reviewed', hint: 'Your review progress' },
          ].map(s => <div key={s.label} className="border-slate-100 px-4 sm:px-6 lg:border-r lg:last:border-0"><p className="text-sm text-slate-500">{s.label}</p><p className="my-2 font-display text-3xl font-bold">{s.value}</p><p className="text-xs text-slate-400">{s.hint}</p></div>)}</section>
          <div className="mb-5 flex flex-wrap items-center justify-between gap-4"><div className="min-w-0"><h2 className="font-display text-xl font-bold">Claim-by-claim review</h2><p className="mt-1 break-words text-sm text-slate-500">{state.document}</p></div><button className="btn-secondary" onClick={() => setTab('Document')}><Upload size={16}/>New document</button></div>
          <div className="mb-5 flex flex-wrap gap-3"><label className="flex min-w-48 flex-1 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-slate-400"><Search size={18}/><input aria-label="Search claims and references" className="w-full min-w-0 py-3 text-sm text-slate-700 outline-none" value={query} placeholder="Search claims or references…" onChange={e => setQuery(e.target.value)}/></label><select className="input w-auto max-w-full" aria-label="Filter verdicts" value={filter} onChange={e => setFilter(e.target.value)}>{['All verdicts', ...statuses].map(s => <option key={s}>{s}</option>)}</select><button className="btn-secondary" onClick={() => download('vericite-claims.csv', csv(state.claims), 'text/csv')}>Export CSV</button></div>
          <div className="grid items-start gap-5 lg:grid-cols-2"><section aria-label="Extracted claims" className="space-y-3">{visible.map((r) => <button key={r.id} className={`w-full rounded-xl border bg-white p-5 text-left transition-colors hover:border-brand-500 ${row?.id === r.id ? 'border-brand-500 ring-1 ring-brand-500' : 'border-slate-200'}`} onClick={() => setSelected(r.id)} aria-pressed={row?.id === r.id}><div className="flex flex-wrap items-center justify-between gap-2"><span className="text-xs font-bold tracking-wider text-slate-400">CLAIM {String(state.claims.indexOf(r) + 1).padStart(2, '0')}</span><Badge status={r.status}/></div><h3 className="my-4 text-base font-medium leading-7">{r.claim}</h3><div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-400"><span className="flex items-center gap-1"><BookOpen size={14}/>{r.markers.join(', ') || 'No citation'}</span><span>{state.reviews[r.id]?.decision || 'Awaiting review'}</span></div>{r.flags.length > 0 && <div className="mt-3 flex items-start gap-2 border-t border-slate-100 pt-3 text-xs text-amber-700"><AlertTriangle size={14}/>{r.flags.join(' · ')}</div>}</button>)}{!visible.length && <div className="panel py-12 text-center"><Search className="mx-auto mb-4 text-slate-400"/><h3 className="font-semibold">No matching claims</h3><p className="my-3 text-sm text-slate-500">Try another search or verdict filter.</p><button className="btn-secondary" onClick={() => { setQuery(''); setFilter('All verdicts'); }}>Clear filters</button></div>}</section>{row && <Evidence key={row.id} row={row} review={state.reviews[row.id]} attachments={state.attachments.filter(a => a.claimId === row.id)} availableFiles={new Set(Object.keys(sourceUrls))} onReview={review} onAttach={attach} onOpen={id => { const url = fileUrls.current[id]; if (url) window.open(url, '_blank', 'noopener,noreferrer'); }} onRemove={removeAttachment}/>}</div>
        </>}
        <footer className="mt-9 flex flex-wrap justify-between gap-3 text-xs leading-6 text-slate-400"><span className="flex items-center gap-2"><ShieldCheck size={15}/>Evidence first. Human judgment always.</span><span>veriCite · Problem statement 03</span></footer>
      </div>
    </main>
  </div>;
}
