import {fetchJson, jsonRequest} from './runs';

export const FEEDBACK_CATEGORIES = [
  'Bug',
  'Security',
  'Results quality',
  'Feature request',
  'Other',
] as const;
export type FeedbackCategory = (typeof FEEDBACK_CATEGORIES)[number];

export function submitFeedback(submission: {
  category: FeedbackCategory;
  message: string;
  diagnostics: string;
  url: string;
  run_id?: string;
}): Promise<{id: string; status: string}> {
  return fetchJson('/api/feedback', jsonRequest(submission, true));
}
