export interface VerificationStatus {
  job_id: string;
  job_state: 'queued' | 'running' | 'completed' | 'failed';
  current_stage: number | null;
  error_message: string | null;
  report?: { stage_errors: string[] };
}
const API_BASE = import.meta.env?.VITE_API_URL?.replace(/\/$/, '') ?? '';
export const verificationEnabled = Boolean(API_BASE || import.meta.env?.DEV);
async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === 'string' ? body.detail : `API request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}
export function checkHealth() {
  return request<{ status: string; providers: string[] }>('/api/health');
}
export function submitDocument(text: string, filename = 'document.txt', signal?: AbortSignal) {
  return request<{ job_id: string; status: string }>('/api/verify', {
    signal, method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, filename }),
  });
}
export function getJobStatus(jobId: string, signal?: AbortSignal) {
  return request<VerificationStatus>(`/api/verify/${encodeURIComponent(jobId)}`, { signal });
}
export interface VerificationRow {
  extraction_error?: string | null;
  id: string;
  text: string;
  marker: string | null;
  reference: string | null;
  doi: string | null;
  mapping: 'mapped' | 'ambiguous' | 'unmatched' | null;
  assessment: {
    assessment_status: 'assessed' | 'unable_to_assess' | 'failed';
    semantic_verdict: 'SUPPORTED' | 'PARTLY_SUPPORTED' | 'UNSUPPORTED' | 'CONTRADICTORY' | null;
    explanation: string;
    issue_flags: string[];
  } | null;
  evidence: { verbatim_text: string; section: string | null; page: number | null }[];
}
export function getJobClaims(jobId: string, signal?: AbortSignal) {
  return request<{ rows: VerificationRow[] }>(`/api/verify/${encodeURIComponent(jobId)}/claims`, { signal });
}
export function getJobReport(jobId: string) {
  return request<unknown>(`/api/verify/${encodeURIComponent(jobId)}/report`);
}
export function searchEvidence(query: string, limit = 5) {
  return request<unknown>(`/api/evidence/search?q=${encodeURIComponent(query)}&limit=${limit}`);
}
export function checkOpenAccess(doi: string) {
  return request<unknown>(`/api/evidence/open-access?doi=${encodeURIComponent(doi)}`);
}
