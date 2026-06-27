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

export interface RunTierOption {
  id: RunTier;
  label: string;
  description: string;
  initialHypotheses: number;
  iterations: number;
  evolvedHypotheses: number;
  tournamentPairs: number;
  evidenceCount: number;
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
    description: 'Quick directional pass for narrowing a question.',
    initialHypotheses: 4,
    iterations: 1,
    evolvedHypotheses: 4,
    tournamentPairs: 6,
    evidenceCount: 4,
  },
  {
    id: 'standard',
    label: 'Standard',
    description: 'Balanced run depth for most research sessions.',
    initialHypotheses: 8,
    iterations: 2,
    evolvedHypotheses: 8,
    tournamentPairs: 12,
    evidenceCount: 8,
  },
  {
    id: 'extended',
    label: 'Extended',
    description: 'Broader search with more evolution and ranking.',
    initialHypotheses: 12,
    iterations: 3,
    evolvedHypotheses: 12,
    tournamentPairs: 20,
    evidenceCount: 12,
  },
  {
    id: 'ultra',
    label: 'Ultra',
    description: 'Maximum breadth for high-value exploration.',
    initialHypotheses: 16,
    iterations: 4,
    evolvedHypotheses: 16,
    tournamentPairs: 32,
    evidenceCount: 16,
  },
];

export const FOCUS_OPTIONS: RunFocusOption[] = [
  {
    id: 'prefer_evidence',
    label: 'Prefer evidence',
    description: 'Favors well-supported, feasible hypotheses.',
    icon: 'fact_check',
  },
  {
    id: 'balance',
    label: 'Balanced',
    description: 'Weights novelty, support, and testability evenly.',
    icon: 'balance',
  },
  {
    id: 'prefer_novelty',
    label: 'Prefer novelty',
    description: 'Rewards distinct mechanisms and new experiments.',
    icon: 'auto_awesome',
  },
  {
    id: 'breakthrough',
    label: 'Breakthrough',
    description: 'Explores high-risk, high-impact hypotheses explicitly.',
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

function isLiverFibrosisGoal(goal: string): boolean {
  return /\b(liver fibrosis|masld|mash|hepatic stellate)\b/i.test(goal);
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

function domainRequirements(goal: string): string[] {
  const lower = goal.toLowerCase();
  const requirements: string[] = [];
  if (/\b(cancer|tumou?r|oncolog|drug|therapy|disease|patient)\b/.test(lower)) {
    requirements.push(
      'Treat biomedical safety and translational feasibility as first-class review criteria.',
    );
  }
  if (/\b(novel|unknown|discover|new)\b/.test(lower)) {
    requirements.push(
      'Penalize hypotheses that only restate known mechanisms without a differentiating test.',
    );
  }
  if (/\b(mechanism|pathway|signalling|signaling|regulat)\b/.test(lower)) {
    requirements.push(
      'Make the causal mechanism explicit enough to design a discriminating experiment.',
    );
  }
  return requirements;
}

function domainAttributes(goal: string): string[] {
  const lower = goal.toLowerCase();
  const attributes: string[] = [];
  if (/\b(drug|therapy|clinical|patient|tnbc|cancer|disease)\b/.test(lower)) {
    attributes.push('Translationally plausible');
  }
  if (/\b(novel|discover|unknown|new)\b/.test(lower)) {
    attributes.push('Differentiated from known mechanisms');
  }
  return attributes;
}

function domainCriteria(goal: string): string[] {
  const lower = goal.toLowerCase();
  const criteria: string[] = [];
  if (/\b(mechanism|pathway|signalling|signaling)\b/.test(lower)) {
    criteria.push('Causal pathway clarity');
  }
  if (/\b(glucose|metabolic|mitochond|autophagy|aging|neural)\b/.test(lower)) {
    criteria.push('Measurable biological readout');
  }
  return criteria;
}
