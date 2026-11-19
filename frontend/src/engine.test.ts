import test from 'node:test';
import assert from 'node:assert/strict';
import { extract, sampleClaims, csv, report, initialWorkspace } from './engine';
import { decodeWorkspace, runDemo, validatePdf } from './services';

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
 const result = report(state); assert.match(result.disclaimer, /PDF contents are not parsed/);
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
 await assert.rejects(runDemo({ kind:'text',title:'Test',text:'This claim needs a source.',file:null }, () => {}, c.signal), {name:'AbortError'});
});
test('PDF demo explicitly separates uploaded metadata from sample claims', async () => {
 const result = await runDemo({kind:'pdf',title:'Actual research',text:'',file:new File(['%PDF-1.4\n'],'actual.pdf')}, () => {}, new AbortController().signal);
 assert.equal(result.mode, 'PDF workflow simulation'); assert.equal(result.requestedPdf?.name,'actual.pdf');
 assert.match(result.document, /not extracted from your PDF/); assert.deepEqual(result.claims, sampleClaims());
});
