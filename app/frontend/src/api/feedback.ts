// Pilot feedback API client. Mirrors the /api/feedback endpoint in
// app/feedback.py.

import type {Audience} from '@/workbench/audience_context';
import {clientHeaders, fetchJson} from './runs';

/** Note categories the form offers; mirrors FEEDBACK_CATEGORIES server-side. */
export type FeedbackCategory = 'bug' | 'suggestion' | 'question' | 'praise';

/** A stored feedback note as returned by the backend. */
export interface FeedbackNote {
  id: number;
  audience: string;
  category: FeedbackCategory;
  message: string;
  created_at: number;
}

/**
 * Submits one feedback note.
 *
 * @param input The note body, its category, and the sender's audience.
 * @returns The stored note.
 */
export function submitFeedback(input: {
  message: string;
  category: FeedbackCategory;
  audience: Audience | null;
}): Promise<FeedbackNote> {
  return fetchJson<FeedbackNote>('/api/feedback', {
    method: 'POST',
    headers: {'Content-Type': 'application/json', ...clientHeaders()},
    body: JSON.stringify({
      message: input.message,
      category: input.category,
      audience: input.audience ?? undefined,
    }),
  });
}
