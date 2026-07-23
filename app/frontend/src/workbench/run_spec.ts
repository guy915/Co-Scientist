import type {Interview, RunFocus, RunTier} from '@/api/runs';

/** Chat-inferred setup shown before a run is created. */
export interface InferredRunSpec {
  interviewId?: string;
  title?: string | null;
  goal: string;
  requirements: string[];
  attributes: string[];
  criteria: string[];
  focus: RunFocus;
  tier: RunTier;
  notifyOnCompletion?: boolean;
  completionEmail?: string;
}

/** Maps a completed Agent interview into the run-configuration card model. */
export function interviewToRunSpec(interview: Interview): InferredRunSpec {
  return {
    interviewId: interview.id,
    title: interview.fields.title,
    goal: interview.fields.research_challenge,
    requirements: interview.fields.preferences,
    attributes: interview.fields.focus_area,
    criteria: [],
    focus: 'balance',
    tier: 'standard',
    notifyOnCompletion: false,
    completionEmail: '',
  };
}

/** One compute-tier choice in the run-setup picker. */
export interface RunTierOption {
  id: RunTier;
  label: string;
  description: string;
}

/** One evidence-vs-novelty focus choice in the run-setup picker. */
export interface RunFocusOption {
  id: RunFocus;
  label: string;
  description: string;
}

/**
 * Compute-tier choices shown in the run-setup picker; `id` is sent to the
 * backend as the run's `tier`.
 */
export const TIER_OPTIONS: RunTierOption[] = [
  {
    id: 'express',
    label: 'Express',
    description:
      'Suitable for quick research questions and small-scale experiments.',
  },
  {
    id: 'standard',
    label: 'Standard',
    description:
      'Suitable for medium-sized research questions and experiments.',
  },
  {
    id: 'extended',
    label: 'Extended',
    description: 'Suitable for large-scale research questions and experiments.',
  },
  {
    id: 'ultra',
    label: 'Ultra',
    description:
      'Most compute-intensive, using the largest models for cutting-edge ' +
      'insights.',
  },
];

/**
 * Evidence-vs-novelty tradeoff choices shown in the run-setup picker; `id` is
 * sent to the backend as the run's `focus`.
 */
export const FOCUS_OPTIONS: RunFocusOption[] = [
  {
    id: 'prefer_evidence',
    label: 'Prefer evidence',
    description:
      'Prioritizes well-established methods and data for high-confidence, ' +
      'incremental advances.',
  },
  {
    id: 'balance',
    label: 'Balance',
    description:
      'A mix of established techniques and novel approaches for a ' +
      'comprehensive strategy.',
  },
  {
    id: 'prefer_novelty',
    label: 'Prefer novelty',
    description:
      'Favors unconventional ideas and exploratory methods for creative, ' +
      'higher-risk solutions.',
  },
  {
    id: 'breakthrough',
    label: 'Breakthrough',
    description:
      'Focuses on high-risk, high-reward strategies with the potential for ' +
      'paradigm shifts.',
  },
];

/**
 * Looks up an option's display label by id (e.g. TIER_OPTIONS/FOCUS_OPTIONS),
 * returning `fallback` when the id isn't recognized (missing or legacy value).
 *
 * @param options The option list to search.
 * @param value The stored id to resolve.
 * @param fallback Label to use when `value` matches no option.
 * @returns The matched option's label, or `fallback`.
 */
export function runOptionLabel(
  options: readonly {id: string; label: string}[],
  value: string | undefined,
  fallback: string,
): string {
  return options.find(option => option.id === value)?.label ?? fallback;
}

/**
 * Whether the spec's completion-notification email passes the minimal
 * shape check used to enable "Start research" (anything@anything.tld);
 * trivially true when notification is off.
 */
export function isCompletionEmailValid(spec: InferredRunSpec): boolean {
  if (!spec.notifyOnCompletion) return true;
  return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(spec.completionEmail || '');
}
