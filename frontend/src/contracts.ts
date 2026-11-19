/** Future service contracts only. No HTTP requests or backend implementation. */
import type { Verdict, ReviewDecision } from './types';
export interface TextLocation {
  page: number; // One-based PyMuPDF page number normalized by the future backend.
  bbox: [number, number, number, number] | null;
  startOffset: number | null;
  endOffset: number | null;
}
export interface OriginalPassage {
  text: string;
  sourceDocumentId: string;
  sourceUrl: string | null;
  location: TextLocation;
  retrievedAt: string;
}
export interface VerifiedClaimResponse {
  id: string;
  documentId: string;
  text: string;
  location: TextLocation;
  referenceIds: string[];
  verdict: Verdict;
  explanation: string;
  evidence: OriginalPassage[];
  uncertainty: string;
  requiresHumanReview: boolean;
}
export interface ProcessingJob {
  id: string;
  documentId: string;
  stage: 'queued' | 'extracting' | 'matching' | 'retrieving' | 'verifying' | 'completed' | 'failed';
  progress: number;
  error: { code: string; message: string; retryable: boolean } | null;
}
export interface ReviewRequest { claimId: string; decision: ReviewDecision; note: string }
