import type {RunFocus, RunTier} from '@/api/runs';

/** Chat-inferred setup shown before a run is created. */
export interface InferredRunSpec {
  goal: string;
  requirements: string[];
  attributes: string[];
  criteria: string[];
  focus: RunFocus;
  tier: RunTier;
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
  icon: string;
}

/**
 * Compute-tier choices shown in the run-setup picker; `id` is sent to the
 * backend as the run's `tier`.
 */
export const TIER_OPTIONS: RunTierOption[] = [
  {
    id: 'standard',
    label: 'Standard Run',
    description:
      'Quicker research for testing and refining a well-scoped goal.',
  },
  {
    id: 'advanced',
    label: 'Advanced Run',
    description:
      'More comprehensive exploration for nuanced and diverse hypotheses.',
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
      'Prioritizes well-established methods and data for high-confidence, incremental advances.',
    icon: 'fact_check',
  },
  {
    id: 'balance',
    label: 'Balance',
    description:
      'A mix of established techniques and novel approaches for a comprehensive strategy.',
    icon: 'balance',
  },
  {
    id: 'prefer_novelty',
    label: 'Prefer novelty',
    description:
      'Favors unconventional ideas and exploratory methods for creative, higher-risk solutions.',
    icon: 'auto_awesome',
  },
  {
    id: 'breakthrough',
    label: 'Breakthrough',
    description:
      'Focuses on high-risk, high-reward strategies with the potential for paradigm shifts.',
    icon: 'rocket_launch',
  },
];

// Baseline requirements/attributes/criteria applied to every goal.
// domainPhrases() appends any keyword-triggered extras from DOMAIN_RULES on
// top of these.
const DEFAULT_REQUIREMENTS = [
  'Prioritize mechanistic novelty, plausibility, and direct testability.',
  'Retrieve broader literature evidence and preserve competing mechanisms.',
  'Use tournament ranking and evolution before final synthesis.',
];

const DEFAULT_ATTRIBUTES = [
  'Mechanistically specific',
  'Evidence-grounded',
  'Experiment-ready',
];

const DEFAULT_CRITERIA = [
  'Scientific soundness',
  'Novelty over known mechanisms',
  'Discriminating experimental design',
  'Translational feasibility',
];

/**
 * Infers the run setup from a research goal using the canonical run path.
 *
 * @param rawGoal User-authored research goal.
 * @returns A compact run setup suitable for confirmation in chat.
 */
export function inferRunSpec(rawGoal: string): InferredRunSpec {
  const goal = normalizeWhitespace(rawGoal);
  return {
    goal,
    requirements: [
      ...DEFAULT_REQUIREMENTS,
      ...domainPhrases(goal, 'requirements'),
    ],
    attributes: [...DEFAULT_ATTRIBUTES, ...domainPhrases(goal, 'attributes')],
    criteria: [...DEFAULT_CRITERIA, ...domainPhrases(goal, 'criteria')],
    focus: 'balance',
    tier: 'standard',
  };
}

/**
 * Applies a chat edit to the inferred run setup without exposing form controls.
 *
 * @param current Current inferred setup.
 * @param instruction User-authored edit instruction.
 * @returns The revised run setup.
 */
export function reviseRunSpec(
  current: InferredRunSpec,
  instruction: string,
): InferredRunSpec {
  const note = normalizeWhitespace(instruction);
  // Recompute the baseline from (possibly unchanged) goal text so
  // domain-triggered phrases stay correct if the edit changes the goal.
  const baseline = inferRunSpec(current.goal);
  // Recognize an explicit "change/update/set the goal to '...'" instruction;
  // any other phrasing is treated as a general steering note (see below)
  // rather than a goal replacement.
  const goalMatch = note.match(
    /(?:change|update|set)\s+(?:the\s+)?goal\s+(?:to|as)\s+[""]?(.+?)[""]?$/i,
  );
  const goal = goalMatch?.[1]
    ? normalizeWhitespace(goalMatch[1])
    : current.goal;
  return {
    ...baseline,
    goal,
    focus: current.focus,
    tier: current.tier,
    requirements: [
      ...baseline.requirements,
      // Preserve any requirements the user already added on top of the
      // baseline (e.g. from an earlier revision), then record this edit as a
      // free-text steering note rather than trying to parse it further.
      ...current.requirements.filter(
        requirement => !baseline.requirements.includes(requirement),
      ),
      `Apply steering note: ${note}`,
    ],
    attributes: current.attributes,
    criteria: current.criteria,
  };
}

// Collapses internal whitespace runs to a single space and trims the ends.
function normalizeWhitespace(value: string): string {
  return value.trim().replace(/\s+/g, ' ');
}

// One keyword-triggered addition: when `pattern` matches the (lowercased)
// goal text, `phrase` is appended to the named bucket on top of the
// DEFAULT_* lists.
interface DomainRule {
  pattern: RegExp;
  bucket: 'requirements' | 'attributes' | 'criteria';
  phrase: string;
}

/**
 * Domain-specific phrases appended to the defaults, tagged by bucket.
 *
 * Rules are listed in the exact order each bucket's phrases must be appended;
 * `domainPhrases` filters by bucket and preserves this order.
 */
const DOMAIN_RULES: DomainRule[] = [
  {
    pattern: /\b(cancer|tumou?r|oncolog|drug|therapy|disease|patient)\b/,
    bucket: 'requirements',
    phrase:
      'Treat biomedical safety and translational feasibility as first-class review criteria.',
  },
  {
    pattern: /\b(novel|unknown|discover|new)\b/,
    bucket: 'requirements',
    phrase:
      'Penalize hypotheses that only restate known mechanisms without a differentiating test.',
  },
  {
    pattern: /\b(mechanism|pathway|signalling|signaling|regulat)\b/,
    bucket: 'requirements',
    phrase:
      'Make the causal mechanism explicit enough to design a discriminating experiment.',
  },
  {
    pattern: /\b(drug|therapy|clinical|patient|tnbc|cancer|disease)\b/,
    bucket: 'attributes',
    phrase: 'Translationally plausible',
  },
  {
    pattern: /\b(novel|discover|unknown|new)\b/,
    bucket: 'attributes',
    phrase: 'Differentiated from known mechanisms',
  },
  {
    pattern: /\b(mechanism|pathway|signalling|signaling)\b/,
    bucket: 'criteria',
    phrase: 'Causal pathway clarity',
  },
  {
    pattern: /\b(glucose|metabolic|mitochond|autophagy|aging|neural)\b/,
    bucket: 'criteria',
    phrase: 'Measurable biological readout',
  },
];

// Returns the phrases from DOMAIN_RULES whose pattern matches the goal and
// whose bucket is `bucket`, in DOMAIN_RULES order (multiple rules can match
// and contribute to the same bucket).
function domainPhrases(goal: string, bucket: DomainRule['bucket']): string[] {
  const lower = goal.toLowerCase();
  return DOMAIN_RULES.filter(
    rule => rule.bucket === bucket && rule.pattern.test(lower),
  ).map(rule => rule.phrase);
}
