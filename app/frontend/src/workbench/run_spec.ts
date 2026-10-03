import type {ChatSummary, Run} from '@/api/runs';
import type {
  Interview,
  RunAttribute,
  RunCriterion,
  RunFocus,
  RunTier,
} from '@/api/runs';
import {getStoredApiKey} from '@/lib/client_id';

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

// Joins values with a trailing "or" ("A, B, or C"), matching the run plan's
// categorical-attribute punctuation.
function joinWithOr(values: string[]): string {
  if (values.length === 1) return values[0];
  if (values.length === 2) return `${values[0]} or ${values[1]}`;
  return `${values.slice(0, -1).join(', ')}, or ${values[values.length - 1]}`;
}

function scaledDisplayString(
  name: string,
  scale: {'1'?: string; '3'?: string; '5'?: string},
): string {
  const anchors = (['1', '3', '5'] as const)
    .filter(point => scale[point])
    .map(point => `${point}: ${scale[point]}`);
  return anchors.length ? `${name}: 1-5 scale (${anchors.join(', ')})` : name;
}

function categoricalDisplayString(name: string, values: string[]): string {
  const options = (values ?? []).filter(Boolean);
  return options.length ? `${name} (${joinWithOr(options)})` : name;
}

// Displays either legacy free prose or the structured run-attribute shape.
export function attributeDisplayString(item: RunAttribute): string {
  if (typeof item === 'string') return item;
  if ('scale' in item) return scaledDisplayString(item.name, item.scale);
  return categoricalDisplayString(item.name, item.values);
}

export function criterionDisplayString(item: RunCriterion): string {
  if (typeof item === 'string') return item;
  return `${item.name}: ${item.value}`;
}

export interface PendingRunCreatePayload extends Record<string, unknown> {
  research_goal?: string;
  requirements?: string[];
  attributes?: string[];
  criteria?: string[];
  focus?: RunFocus;
  tier?: RunTier;
  notify_on_completion?: boolean;
  completion_email?: string;
}

export interface LinkedRunTarget {
  chatId: string;
  runId: string;
  chat: ChatSummary | undefined;
  interview: Interview | null;
}

function firstDefined<T>(fallback: T, ...values: (T | undefined)[]): T {
  return values.find(value => value !== undefined) ?? fallback;
}

function whenPresent<A, B>(
  source: A | null | undefined,
  get: (source: A) => B | undefined,
): B | undefined {
  if (source === undefined || source === null) return undefined;
  return get(source);
}

export function recoverySpecForRun(
  target: LinkedRunTarget,
  run: Run,
  payload: PendingRunCreatePayload | undefined,
): InferredRunSpec {
  const setup = run.config.setup;
  const interviewTitle = whenPresent(
    target.interview,
    interview => interview.fields.title,
  );
  const interviewGoal = whenPresent(
    target.interview,
    interview => interview.fields.research_challenge,
  );
  const interviewPreferences = whenPresent(
    target.interview,
    interview => interview.fields.preferences,
  );
  const interviewAttributes = whenPresent(
    target.interview,
    interview => interview.fields.focus_area,
  );
  return {
    interviewId: firstDefined(
      target.chatId,
      whenPresent(target.interview, interview => interview.id),
    ),
    title: firstDefined(
      whenPresent(target.chat, chat => chat.title),
      interviewTitle,
    ),
    goal: firstDefined(
      run.research_goal,
      whenPresent(setup, value => value.goal),
      whenPresent(payload, value => value.research_goal),
      interviewGoal,
    ),
    requirements: firstDefined(
      [],
      whenPresent(setup, value => value.requirements),
      whenPresent(payload, value => value.requirements),
      interviewPreferences,
    ),
    attributes: firstDefined(
      [],
      whenPresent(setup, value => value.attributes.map(attributeDisplayString)),
      whenPresent(payload, value => value.attributes),
      interviewAttributes,
    ),
    criteria: firstDefined(
      [],
      whenPresent(setup, value => value.criteria.map(criterionDisplayString)),
      whenPresent(payload, value => value.criteria),
    ),
    focus: firstDefined(
      'balance',
      whenPresent(setup, value => value.focus),
      run.config.focus,
      whenPresent(payload, value => value.focus),
    ),
    tier: firstDefined(
      'standard',
      whenPresent(setup, value => value.tier),
      run.config.tier,
      whenPresent(payload, value => value.tier),
    ),
    notifyOnCompletion: firstDefined(
      false,
      whenPresent(payload, value => value.notify_on_completion),
    ),
    completionEmail: firstDefined(
      '',
      whenPresent(payload, value => value.completion_email),
    ),
  };
}
