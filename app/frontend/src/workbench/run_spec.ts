import type {RunFocus, RunTier} from '@/api/runs';
import {isLiverFibrosisGoal} from '@/lib/demo_domains';

/** Chat-inferred setup shown before a run is created. */
export interface InferredRunSpec {
  goal: string;
  requirements: string[];
  attributes: string[];
  criteria: string[];
  focus: RunFocus;
  tier: RunTier;
}

export interface RunTierOption {
  id: RunTier;
  label: string;
  description: string;
}

export interface RunFocusOption {
  id: RunFocus;
  label: string;
  description: string;
  icon: string;
}

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
      'Most compute-intensive, using the largest models for cutting-edge insights.',
  },
];

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

const LIVER_FIBROSIS_REQUIREMENTS = [
  'The hypothesis must propose a specific, mechanistic pathway for reversing established liver fibrosis.',
  'The hypothesis must include a specific, actionable intervention based on the proposed mechanism.',
  'The intervention must specifically target one or more of the following: epigenetic regulators, hepatic stellate cell biology, or stromal-immune interactions.',
  'The hypothesis must be truly novel and not a reiteration of existing well-known theories.',
  'The hypothesis must be formulated in a clearly testable manner, allowing for experimental verification or falsification.',
  'The idea must include concrete, detailed experimental validation strategies to test the hypothesis.',
  'Experimental validation strategies must utilize human-relevant models (e.g., organoids, precision-cut liver slices, humanized mouse models, patient-derived primary cells).',
  'The idea must include a comprehensive assessment of potential scientific, technical, and translational pitfalls and challenges associated with the proposed hypothesis and intervention.',
  'The focus must be exclusively on MASLD/MASH (Metabolic Dysfunction-Associated Steatotic Liver Disease / Metabolic Dysfunction-Associated Steatohepatitis) liver fibrosis.',
  'The intervention must aim to reverse *established* fibrosis, not merely prevent its progression or onset.',
];

const LIVER_FIBROSIS_ATTRIBUTES = [
  "Primary Target: Identify the primary biological target pathway: 'Epigenetic Regulators,' 'Hepatic Stellate Cell Biology,' or 'Stromal-Immune Interactions'.",
  'Novelty Score: Rate the novelty of the hypothesis on a scale from 1 to 5 (1: incremental, 3: reasonably novel, 5: groundbreaking).',
  'Testability Score: Rate the testability of the hypothesis on a scale from 1 to 5 (1: extremely difficult/impractical to test, 3: testable with significant effort, 5: highly feasible with standard methods).',
  'Human-Relevance of Models: Rate the human-relevance of the proposed experimental models on a scale from 1 to 5 (1: exclusively animal/non-human models, 3: mix of human-relevant and less relevant, 5: predominantly human-relevant models).',
  'Feasibility of Intervention: Rate the overall feasibility and specificity of the proposed intervention on a scale from 1 to 5.',
];

const LIVER_FIBROSIS_CRITERIA = [
  'Mechanistic specificity',
  'Novelty against known fibrosis pathways',
  'Direct experimental testability',
  'Human-relevant validation strategy',
  'Feasible translational path',
  'Potential pitfalls and mitigation strategy',
];

/**
 * Infers the run setup from a research goal using the canonical run path.
 *
 * @param rawGoal User-authored research goal.
 * @returns A compact run setup suitable for confirmation in chat.
 */
export function inferRunSpec(rawGoal: string): InferredRunSpec {
  const goal = normalizeWhitespace(rawGoal);
  if (isLiverFibrosisGoal(goal)) {
    return {
      goal,
      requirements: LIVER_FIBROSIS_REQUIREMENTS,
      attributes: LIVER_FIBROSIS_ATTRIBUTES,
      criteria: LIVER_FIBROSIS_CRITERIA,
      focus: 'balance',
      tier: 'standard',
    };
  }
  return {
    goal,
    requirements: [...DEFAULT_REQUIREMENTS, ...domainRequirements(goal)],
    attributes: [...DEFAULT_ATTRIBUTES, ...domainAttributes(goal)],
    criteria: [...DEFAULT_CRITERIA, ...domainCriteria(goal)],
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
  const baseline = inferRunSpec(current.goal);
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
      ...current.requirements.filter(
        requirement => !baseline.requirements.includes(requirement),
      ),
      `Apply steering note: ${note}`,
    ],
    attributes: current.attributes,
    criteria: current.criteria,
  };
}

function normalizeWhitespace(value: string): string {
  return value.trim().replace(/\s+/g, ' ');
}

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

function domainPhrases(goal: string, bucket: DomainRule['bucket']): string[] {
  const lower = goal.toLowerCase();
  return DOMAIN_RULES.filter(
    rule => rule.bucket === bucket && rule.pattern.test(lower),
  ).map(rule => rule.phrase);
}

function domainRequirements(goal: string): string[] {
  return domainPhrases(goal, 'requirements');
}

function domainAttributes(goal: string): string[] {
  return domainPhrases(goal, 'attributes');
}

function domainCriteria(goal: string): string[] {
  return domainPhrases(goal, 'criteria');
}
