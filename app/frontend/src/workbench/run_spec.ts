import type {Interview, RunFocus, RunTier} from '@/api/runs';
import {getStoredApiKey} from '@/lib/api_key';

/**
 * The only run type free usage (no API key of one's own) may start; the
 * backend refuses any other (app/free_usage.py).
 */
export const FREE_RUN_TIER: RunTier = 'express';

/** The default run type: Standard with an API key, else the free tier. */
export function defaultRunTier(): RunTier {
  return getStoredApiKey() ? 'standard' : FREE_RUN_TIER;
}

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
    tier: defaultRunTier(),
    notifyOnCompletion: false,
    completionEmail: '',
  };
}

/**
 * The plan card's in-place editor state: plain strings/arrays for the four
 * fields the interview derives (goal, focus area, preferences, title).
 * Kept distinct from `InferredRunSpec` because the editor's title is always
 * a string (empty means unset), where the card's is `string | null`.
 */
export interface EditedSpecFields {
  goal: string;
  title: string;
  attributes: string[];
  requirements: string[];
}

/**
 * Maps the editor's local field values onto the `PUT /fields` request
 * shape. A blank title is sent as `null`, matching how an unedited card
 * (never having set a title) already reads.
 */
export function buildInterviewFieldsPayload(
  values: EditedSpecFields,
): Interview['fields'] {
  return {
    research_challenge: values.goal,
    focus_area: values.attributes,
    preferences: values.requirements,
    title: values.title.trim() ? values.title : null,
  };
}

/**
 * Maps a `PUT /fields` response back onto the run-spec field names, for
 * merging into the draft/confirmed spec after a save. The server may not
 * have stored the edit exactly as sent (it trims list entries), so the
 * editor adopts this rather than assuming its own local values landed.
 */
export function applyEditedInterviewFields(
  interview: Interview,
): Pick<
  InferredRunSpec,
  'interviewId' | 'title' | 'goal' | 'attributes' | 'requirements'
> {
  return {
    interviewId: interview.id,
    title: interview.fields.title,
    goal: interview.fields.research_challenge,
    attributes: interview.fields.focus_area,
    requirements: interview.fields.preferences,
  };
}

/** One compute-tier choice in the run-setup picker. */
export interface RunTierOption {
  id: RunTier;
  label: string;
  description: string;
  /** Set when free usage cannot start this run type. */
  disabled?: boolean;
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
 * The run-type choices open to the current user: every tier with an API key;
 * with none, the non-free tiers are disabled and say why.
 */
export function availableTierOptions(): RunTierOption[] {
  if (getStoredApiKey()) return TIER_OPTIONS;
  return TIER_OPTIONS.map(option =>
    option.id === FREE_RUN_TIER
      ? option
      : {
          ...option,
          disabled: true,
          description: 'Requires your own API key (Settings > Model).',
        },
  );
}

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
 * The minimal address-shape check (anything@anything.tld) used both to
 * decide whether a typed address turns notification on, and to gate
 * "Start research" below.
 */
export function isValidCompletionEmail(email: string): boolean {
  return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email);
}

/**
 * Whether the spec's completion-notification email passes the minimal
 * shape check used to enable "Start research"; trivially true when
 * notification is off. `notifyOnCompletion` is derived from the email's
 * own validity (see `CompletionNotification`), so a half-typed address
 * never sets it -- it stays a normal, silent "no email" rather than
 * something that can block starting a run.
 */
export function isCompletionEmailValid(spec: InferredRunSpec): boolean {
  if (!spec.notifyOnCompletion) return true;
  return isValidCompletionEmail(spec.completionEmail || '');
}
