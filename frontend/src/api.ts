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
const jobTokens = new Map<string, string>();
function jobHeaders(id: string) {
  const token = jobTokens.get(id);
  return token ? { Authorization: `Bearer ${token}` } : undefined;
}
export async function submitDocument(text: string, filename = 'document.txt', signal?: AbortSignal, accessCode?: string) {
  const job = await request<{ job_id: string; status: string; access_token?: string }>('/api/verify', {
    signal, method: 'POST', headers: { 'Content-Type': 'application/json', ...(accessCode ? { 'X-Verification-Key': accessCode } : {}) },
    body: JSON.stringify({ text, filename }),
  });
  if (job.access_token) jobTokens.set(job.job_id, job.access_token);
  return job;
}
export function getJobStatus(jobId: string, signal?: AbortSignal) {
  return request<VerificationStatus>(`/api/verify/${encodeURIComponent(jobId)}`, { signal, headers: jobHeaders(jobId) });
}
export interface VerificationRow {
  extraction_error?: string | null;
  id: string;
  text: string;
  review_reason?: string | null;
  coverage?: string;
  marker: string | null;
  reference: string | null;
  doi: string | null;
  source_url?: string | null;
  mapping: 'mapped' | 'ambiguous' | 'unmatched' | null;
  assessment: {
    assessment_status: 'assessed' | 'unable_to_assess' | 'failed';
    semantic_verdict: 'SUPPORTED' | 'PARTLY_SUPPORTED' | 'UNSUPPORTED' | 'CONTRADICTORY' | 'POSSIBLY_OUTDATED' | null;
    explanation: string;
    confidence_basis?: string;
    update_evidence?: { title: string; year: string; url: string; quote: string } | null;
    issue_flags: string[];
  } | null;
  evidence: { verbatim_text: string; section: string | null; page: number | null }[];
}
export function getJobClaims(jobId: string, signal?: AbortSignal) {
  return request<{ rows: VerificationRow[] }>(`/api/verify/${encodeURIComponent(jobId)}/claims`, { signal, headers: jobHeaders(jobId) });
}
export function getJobReport(jobId: string) {
  return request<unknown>(`/api/verify/${encodeURIComponent(jobId)}/report`, { headers: jobHeaders(jobId) });
}
export function searchEvidence(query: string, limit = 5) {
  return request<unknown>(`/api/evidence/search?q=${encodeURIComponent(query)}&limit=${limit}`);
}
export function checkOpenAccess(doi: string) {
  return request<unknown>(`/api/evidence/open-access?doi=${encodeURIComponent(doi)}`);
}
