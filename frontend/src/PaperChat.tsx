import { useState } from 'react';
import { statuses } from './engine';
import type { Workspace } from './types';
interface Message { question: string; answer: string; index?: number }
export function PaperChat({state}: {state: Workspace}) {
 const [thread,setThread]=useState<Message[]>([]),[question,setQuestion]=useState('');
 function ask(input:string) {
  const q=input.trim();if(!q)return;
  const rows=state.claims,number=q.match(/claim\s*#?\s*(\d+)/i);
  const terms=q.toLowerCase().match(/[a-z0-9]{3,}/g)||[];
  const matches=rows.map((r,index)=>({index,score:terms.filter(t=>!['the','and','what','for','this','about','does','show','claim'].includes(t)&&(r.claim+' '+r.references.join(' ')).toLowerCase().includes(t)).length})).sort((a,b)=>b.score-a.score);
  let index=number?Number(number[1])-1:matches[0]?.score?matches[0].index:thread.at(-1)?.index;
  let answer:string;
  if(/summari|summary|overview/i.test(q)){index=undefined;answer=state.document+'\n'+rows.length+' candidate claims. '+rows.filter(r=>r.references.length).length+' have mapped references.\n'+statuses.map(s=>[s,rows.filter(r=>r.status===s).length] as const).filter(([,n])=>n).map(([s,n])=>s+' · '+n).join('\n');}
  else if(!number&&/issues|flagged|missing citations/i.test(q)){index=undefined;answer=rows.flatMap((r,i)=>r.flags.length?['Claim '+(i+1)+' — '+r.flags.join(', ')]:[]).join('\n')||'No citation issues are recorded.';}
  else if(index!==undefined&&rows[index]){const r=rows[index];answer='Claim '+(index+1)+' — '+r.claim+'\n'+r.status+' · '+r.reason+'\n'+r.evidence+'\n'+(r.references.join('\n')||'No mapped reference.');}
  else answer='Try a claim number from 1 to '+rows.length+', a phrase from the paper, or “Show citation issues”.';
  setThread(t=>[...t,{question:q,answer,index}]);setQuestion('');
 }
 return <section className="panel mt-6 max-w-4xl"><h2 className="text-xl font-bold">Ask about this paper</h2><p className="mt-3 text-sm leading-7 text-slate-500">Explore current results by claim number, keyword or citation. This is a local rule-based demo, not an LLM chat or a reading of the full PDF.</p><div className="my-5 flex flex-wrap gap-2">{['Summarize the paper','Show citation issues','Explain claim 1'].map(q=><button className="btn-secondary" key={q} onClick={()=>ask(q)}>{q}</button>)}</div><div aria-live="polite">{thread.map((m,i)=><article key={i} className="my-6"><p className="ml-auto w-fit max-w-full rounded-xl bg-brand-700 px-4 py-2 text-sm text-white">{m.question}</p><p className="mt-4 whitespace-pre-line break-words text-sm leading-7">{m.answer}</p></article>)}</div><form className="mt-6 flex flex-wrap gap-2" onSubmit={e=>{e.preventDefault();ask(question);}}><input className="input min-w-40 flex-1" aria-label="Question about the current paper" placeholder="Ask a follow-up question…" value={question} onChange={e=>setQuestion(e.target.value)}/><button className="btn" disabled={!question.trim()}>Send</button></form></section>;
}
