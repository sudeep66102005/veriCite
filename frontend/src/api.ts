export interface VerificationStatus {
  job_id: string;
  job_state: 'queued' | 'running' | 'completed' | 'failed';
  current_stage: number | null;
  error_message: string | null;
  report?: unknown;
}
const API_BASE = import.meta.env.VITE_API_URL?.replace(/\/$/, '') ?? '';
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
export function submitDocument(text: string, filename = 'document.txt') {
  return request<{ job_id: string; status: string }>('/api/verify', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, filename }),
  });
}
export function getJobStatus(jobId: string) {
  return request<VerificationStatus>(`/api/verify/${encodeURIComponent(jobId)}`);
}
export function getJobClaims(jobId: string) {
  return request<{ claims: unknown[] }>(`/api/verify/${encodeURIComponent(jobId)}/claims`);
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
