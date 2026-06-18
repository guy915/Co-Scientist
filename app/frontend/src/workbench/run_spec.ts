import type {RunProfile} from '@/api/runs';

/** Chat-inferred setup shown before a run is created. */
export interface InferredRunSpec {
  goal: string;
  profile: RunProfile;
  mode: string;
  constraints: string[];
  output: string;
}

const STANDARD_CONSTRAINTS = [
  'Prioritize mechanistic novelty, plausibility, and direct testability.',
  'Retrieve literature evidence when available and label unsupported claims.',
  'Keep the initial pass compact so results arrive quickly.',
];

const ADVANCED_CONSTRAINTS = [
  'Prioritize mechanistic novelty, plausibility, and direct testability.',
  'Retrieve broader literature evidence and preserve competing mechanisms.',
  'Use a deeper tournament/evolution pass before final synthesis.',
];

/**
 * Infers the MVP run setup from a research goal and simple effort profile.
 *
 * @param rawGoal User-authored research goal.
 * @param profile Standard or Advanced effort profile.
 * @returns A compact run setup suitable for confirmation in chat.
 */
export function inferRunSpec(
  rawGoal: string,
  profile: RunProfile,
): InferredRunSpec {
  const goal = normalizeWhitespace(rawGoal);
  const constraints =
    profile === 'advanced' ? ADVANCED_CONSTRAINTS : STANDARD_CONSTRAINTS;
  return {
    goal,
    profile,
    mode:
      profile === 'advanced'
        ? 'Advanced hypothesis tournament'
        : 'Standard hypothesis sprint',
    constraints: [...constraints, ...domainConstraints(goal)],
    output:
      'Ranked hypotheses with Elo, mechanisms, evidence links, ranking rationale, and a polished report.',
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
  const lower = note.toLowerCase();
  const profile: RunProfile = lower.includes('advanced')
    ? 'advanced'
    : lower.includes('standard')
      ? 'standard'
      : current.profile;
  const baseline = inferRunSpec(current.goal, profile);
  const goalMatch = note.match(
    /(?:change|update|set)\s+(?:the\s+)?goal\s+(?:to|as)\s+["“]?(.+?)["”]?$/i,
  );
  const goal = goalMatch?.[1] ? normalizeWhitespace(goalMatch[1]) : current.goal;
  return {
    ...baseline,
    goal,
    constraints: [
      ...baseline.constraints,
      `Apply steering note: ${note}`,
    ],
  };
}

function normalizeWhitespace(value: string): string {
  return value.trim().replace(/\s+/g, ' ');
}

function domainConstraints(goal: string): string[] {
  const lower = goal.toLowerCase();
  const constraints: string[] = [];
  if (/\b(cancer|tumou?r|oncolog|drug|therapy|disease|patient)\b/.test(lower)) {
    constraints.push(
      'Treat biomedical safety and translational feasibility as first-class review criteria.',
    );
  }
  if (/\b(novel|unknown|discover|new)\b/.test(lower)) {
    constraints.push(
      'Penalize hypotheses that only restate known mechanisms without a differentiating test.',
    );
  }
  if (/\b(mechanism|pathway|signalling|signaling|regulat)\b/.test(lower)) {
    constraints.push(
      'Make the causal mechanism explicit enough to design a discriminating experiment.',
    );
  }
  return constraints;
}
