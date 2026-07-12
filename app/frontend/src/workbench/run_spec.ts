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
