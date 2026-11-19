import test from 'node:test';
import assert from 'node:assert/strict';
import { extract, sampleClaims, csv, report, initialWorkspace } from './engine';
import { decodeWorkspace, runAnalysis, runVerification, validatePdf } from './services';

test('maps numeric citations without treating bibliography as claims', () => {
 const rows = extract('An intervention improves results [1].\nReferences\n[1] Smith 2020. Study.');
 assert.equal(rows.length, 1); assert.equal(rows[0].references.length, 1);
 assert.equal(rows[0].status, 'Unverified'); assert.equal(rows[0].confidence, null);
});
test('flags missing and unmatched citations', () => {
 assert.deepEqual(extract('This assertion has no citation.')[0].flags, ['Missing citation']);
 assert.deepEqual(extract('A finding is supported [7].')[0].flags, ['Unmatched reference']);
});
test('maps author-year references', () => assert.equal(extract('The results improved (Smith, 2020).\nReferences\nSmith (2020). A study.')[0].references.length, 1));
test('custom input never receives sample verdicts', () => {
 const rows = extract(sampleClaims().map(r => r.claim).join('\n'));
 assert.ok(rows.every(r => r.status === 'Unverified' && r.confidence === null));
});
test('sample covers all six verdicts', () => assert.equal(new Set(sampleClaims().map(r => r.status)).size, 6));
test('CSV escapes text and guards spreadsheet formula cells', () => {
 const row = { ...sampleClaims()[0], claim: 'a,"b"\nc' };
 assert.match(csv([row]), /"a,""b""\nc"/);
 assert.match(csv([{ ...row, claim: '=SUM(1,2)' }]), /"'=SUM\(1,2\)"/);
});
test('reports preserve mode, source metadata and review history', () => {
 const state = initialWorkspace(); state.history.push({claimId:'claim-1',decision:'Reviewed',note:'Check',at:new Date().toISOString()});
 const result = report(state); assert.match(result.disclaimer, /illustrative paraphrases/);
 const restored=decodeWorkspace(JSON.stringify(result)); assert.equal(restored?.document,state.document); assert.deepEqual(restored?.history,state.history);
});
test('invalid persisted state is rejected without crashing', () => {
 assert.equal(decodeWorkspace('{'), null);
 assert.equal(decodeWorkspace(JSON.stringify({ ...initialWorkspace(), claims: [{ id:'bad' }] })), null);
});
test('PDF validation rejects unsupported, empty and oversized files', async () => {
 await assert.rejects(validatePdf(new File(['hello'], 'paper.pdf')), /PDF header/);
 await assert.rejects(validatePdf(new File([], 'paper.pdf')), /empty/);
 await assert.rejects(validatePdf(new File(['%PDF-'], 'paper.txt')), /Choose a PDF/);
 await assert.rejects(validatePdf(new File([new Uint8Array(10 * 1024 * 1024 + 1)], 'paper.pdf')), /10 MB/);
 await validatePdf(new File(['%PDF-1.4\n'], 'paper.pdf'));
});
test('cancelled workflow does not produce a replacement report', async () => {
 const c = new AbortController(); c.abort();
 await assert.rejects(runAnalysis({ kind:'text',title:'Test',text:'This claim needs a source.',file:null }, () => {}, c.signal), {name:'AbortError'});
});

function makePdf(lines: string[], filename = 'paper.pdf'): File {
 const stream = ['BT /F1 12 Tf 72 720 Td 18 TL', ...lines.map((line, i) => `${i ? 'T* ' : ''}(${line}) Tj`), 'ET'].join('\n');
 const objects = [
  '<< /Type /Catalog /Pages 2 0 R >>',
  '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
  '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
  '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
  `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`,
 ];
 let pdf = '%PDF-1.4\n';
 const offsets = objects.map((object, i) => {
  const offset = pdf.length;
  pdf += `${i + 1} 0 obj\n${object}\nendobj\n`;
  return offset;
 });
 const xref = pdf.length;
 pdf += 'xref\n0 6\n0000000000 65535 f \n';
 for (const offset of offsets) pdf += `${String(offset).padStart(10, '0')} 00000 n \n`;
 pdf += `trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
 return new File([pdf], filename, { type: 'application/pdf' });
}

const analyzePdf = (file: File) =>
 runAnalysis({ kind: 'pdf', title: '', text: '', file }, () => {}, new AbortController().signal);

test('different PDF contents produce different claims and references even with the same filename', async () => {
 const first = await analyzePdf(makePdf(['Solar panels power the observatory [1].', 'References', '[1] Solar power study.']));
 const second = await analyzePdf(makePdf(['Coastal forests reduce flood damage [1].', 'References', '[1] Coastal forest study.']));
 assert.deepEqual(first.claims.map(row => row.claim), ['Solar panels power the observatory [1].']);
 assert.deepEqual(second.claims.map(row => row.claim), ['Coastal forests reduce flood damage [1].']);
 assert.deepEqual(first.claims[0].references, ['[1] Solar power study.']);
 assert.deepEqual(second.claims[0].references, ['[1] Coastal forest study.']);
 for (const result of [first, second]) {
  assert.equal(result.document, 'paper.pdf');
  assert.equal(result.requestedPdf?.name, 'paper.pdf');
  assert.equal(result.mode, 'PDF · unverified');
  assert.equal(result.claims[0].status, 'Unverified');
  assert.deepEqual(decodeWorkspace(JSON.stringify(result)), result);
 }
});

test('unreadable and textless PDFs fail without returning a sample report', async () => {
 await assert.rejects(analyzePdf(new File(['%PDF-1.4\n'], 'broken.pdf')), /Could not read this PDF/);
 await assert.rejects(analyzePdf(makePdf([])), /no selectable text/);
});

test('verification submits manuscript text and only displays verdicts with traceable evidence', async t => {
 const manuscript = 'Solar panels power the observatory [1].';
 const base = {
  id: 'link-1', text: manuscript, marker: '[1]', reference: '[1] Solar power study.',
  doi: '10.1234/study', mapping: 'mapped',
  assessment: { assessment_status: 'assessed', semantic_verdict: 'SUPPORTED', explanation: 'The source reports the same result.', issue_flags: [] },
 };
 const fetch = t.mock.method(globalThis, 'fetch', async (path: string, request?: RequestInit) => {
  if (path === '/api/verify') {
   assert.equal(request?.method, 'POST');
   assert.equal(JSON.parse(String(request.body)).text, manuscript);
   return Response.json({ job_id: 'job-1' }, { status: 202 });
  }
  if (path === '/api/verify/job-1') return Response.json({ job_state: 'completed', report: { stage_errors: [] } });
  assert.equal(path, '/api/verify/job-1/claims');
  return Response.json({ rows: [
   { ...base, evidence: [{ verbatim_text: manuscript, page: 2, section: 'Results' }] },
   { ...base, id: 'link-2', evidence: [] },
  ] });
 });
 const { workspace } = await runVerification(
  { kind: 'text', title: 'Research test', text: manuscript, file: null }, () => {}, new AbortController().signal
 );
 assert.equal(fetch.mock.calls.length, 3);
 assert.deepEqual(workspace.claims.map(row => row.status), ['Supported', 'Unverified']);
 assert.equal(workspace.claims[0].section, 'Results · Page 2');
 assert.equal(workspace.claims[0].source, 'https://doi.org/10.1234/study');
 assert.deepEqual(decodeWorkspace(JSON.stringify(workspace)), workspace);
});
