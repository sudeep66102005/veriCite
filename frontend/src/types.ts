export const verdicts = ['Supported', 'Partly supported', 'Unsupported', 'Contradictory', 'Possibly outdated', 'Unverified'] as const;
export type Verdict = typeof verdicts[number];
export type Confidence = 'High' | 'Medium' | 'Low' | null;
export type ReviewDecision = 'Reviewed' | 'Needs follow-up';
export type Mode = 'API verification' | 'Sample demo' | 'Custom text · unverified' | 'PDF · unverified' | 'PDF workflow simulation';
export interface Claim {
  id: string;
  claim: string;
  markers: string[];
  references: string[];
  status: Verdict;
  confidence: Confidence;
  confidenceBasis?: string;
  updateEvidence?: { url: string; title: string; year: string; quote: string };
  evidence: string;
  section: string;
  reason: string;
  flags: string[];
  source: string | null;
}
export interface Review {
  claimId: string;
  decision: ReviewDecision;
  note: string;
  at: string;
}
export interface FileMetadata { name: string; size: number; type: string }
export interface SourceAttachment extends FileMetadata { id: string; claimId: string; addedAt: string }
export interface Workspace {
  schemaVersion: 2;
  document: string;
  mode: Mode;
  claims: Claim[];
  reviews: Record<string, Review>;
  history: Review[];
  attachments: SourceAttachment[];
  requestedPdf: FileMetadata | null;
}
export interface PipelineStep { title: string; detail: string }
export interface VerificationReport extends Workspace {
  product: string;
  generatedAt: string;
  disclaimer: string;
  attachmentNotice: string;
}
