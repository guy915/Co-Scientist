import type {
  CitationRow,
  Evidence,
  Hypothesis,
  MatchRow,
  Report,
  Review,
  Run,
  RunConfig,
  RunEvent,
  RunFocus,
  RunSetupConfig,
  RunStatus,
  RunTier,
  SafetyDecision,
} from './run_types';
import {isLiverFibrosisGoal} from '@/lib/demo_domains';

export interface OfflineRunRecord {
  run: Run;
  hypotheses: Hypothesis[];
  evidence: Evidence[];
  matches: MatchRow[];
  reviews: Review[];
  citations: CitationRow[];
  report: Report | null;
  events: RunEvent[];
  safety: SafetyDecision[];
}

const DEMO_GOALS = [
  {
    id: 'demo-mash-fibrosis',
    goal: 'Generate a novel, testable hypothesis for reversing established liver fibrosis in MASLD/MASH by targeting epigenetic regulators.',
  },
  {
    id: 'demo-ferroptosis',
    goal: 'What are the key molecular regulators of ferroptosis in pancreatic cancer cells, and how might their modulation enhance chemotherapy sensitivity?',
  },
  {
    id: 'demo-synaptic-pruning',
    goal: 'How does synaptic pruning in the prefrontal cortex contribute to cognitive flexibility during adolescent development?',
  },
  {
    id: 'demo-antibiotic-resistance',
    goal: 'What mechanisms drive antibiotic resistance in Staphylococcus aureus biofilms, and which metabolic pathways could be targeted to restore susceptibility?',
  },
] as const;

export const nowSeconds = () => Math.floor(Date.now() / 1000);

export function defaultSetup(
  goal: string,
  focus: RunFocus = 'balance',
  tier: RunTier = 'standard',
): RunSetupConfig {
  return {
    goal,
    requirements: [
      'Prioritize mechanistic novelty, plausibility, and direct testability.',
      'Retrieve broader literature evidence and preserve competing mechanisms.',
      'Use tournament ranking and evolution before final synthesis.',
      'Penalize hypotheses that only restate known mechanisms without a differentiating test.',
    ],
    attributes: [
      'Mechanism novelty',
      'Human relevance',
      'Clinical translatability',
      'Experimental tractability',
    ],
    criteria: [
      'Scientific soundness',
      'Specific biological mechanism',
      'Evidence-aware novelty',
      'Clear experimental readout',
    ],
    focus,
    tier,
  };
}

export function runFor(
  id: string,
  goal: string,
  createdAt: number,
  config: RunConfig = {},
  status: RunStatus = 'completed',
): Run {
  const setup = config.setup ?? defaultSetup(goal, config.focus, config.tier);
  const run: Run = {
    id,
    research_goal: goal,
    run_mode: 'default',
    profile: 'default',
    status,
    provider: 'mock',
    config: {...config, setup, focus: setup.focus, tier: setup.tier},
    is_demo: id.startsWith('demo-'),
    created_at: createdAt,
    updated_at: createdAt + 60,
    completed_at: status === 'completed' ? createdAt + 60 : null,
    error: null,
    top_elo: null,
  };
  // Mirror the backend: the run list carries the run's highest Elo so the home
  // surface never fetches hypotheses just to show a score.
  if (status === 'completed') {
    const elos = artifactsFor(run).hypotheses.map(h => h.elo_rating);
    run.top_elo = elos.length ? Math.max(...elos) : null;
  }
  return run;
}

function hypothesisTitles(goal: string): string[] {
  if (isLiverFibrosisGoal(goal)) {
    return [
      'Temporal restriction of downstream epigenetic effectors',
      'Stellate-cell enhancer remodeling through transient chromatin release',
      'Macrophage-stellate feedback interruption after matrix priming',
      'Metabolic rerouting to expose reversible fibrotic memory',
    ];
  }
  if (/ferroptosis|pancreatic/i.test(goal)) {
    return [
      'Mitochondrial feedback hypothesis',
      'Lipid peroxide buffering threshold hypothesis',
      'Iron-trafficking checkpoint hypothesis',
      'GPX4-adaptive resistance switch hypothesis',
    ];
  }
  if (/synaptic|prefrontal/i.test(goal)) {
    return [
      'Microglial timing-window pruning hypothesis',
      'Complement-gated flexibility hypothesis',
      'Activity-dependent dendritic retention hypothesis',
      'Adolescent inhibitory-balance hypothesis',
    ];
  }
  return [
    'Metabolic refuge disruption hypothesis',
    'Biofilm redox-state vulnerability hypothesis',
    'Quorum-linked susceptibility restoration hypothesis',
    'Stress-response collapse hypothesis',
  ];
}

export function artifactsFor(run: Run): OfflineRunRecord {
  const titles = hypothesisTitles(run.research_goal);
  const base = run.completed_at ?? run.updated_at;
  const hypotheses: Hypothesis[] = titles.map((title, index) => {
    const elo = [1290, 1264, 1248, 1226][index] ?? 1200 - index * 12;
    return {
      id: `${run.id}-h${index + 1}`,
      run_id: run.id,
      parent_id: null,
      generation: index < 2 ? 0 : 1,
      category: title.split(' ').slice(0, 2).join(' '),
      title: `H${index + 1}: ${title}`,
      statement: `In the context of '${run.research_goal}', we hypothesize that ${title.toLowerCase()} will produce a measurable effect through a mechanism distinct from current consensus.`,
      mechanism: `The proposed pathway operates by ${title.toLowerCase()}, with feedback at two checkpoints; the predicted intermediate state is detectable by standard assays.`,
      expected_effect:
        'A measurable shift in the target phenotype without broad, non-specific suppression.',
      experimental_context:
        'Human-relevant organoids, perturbation series, and orthogonal transcriptomic validation.',
      created_by_agent:
        index % 2 === 0 ? 'Generation agent' : 'Evolution agent',
      created_at: base - 50 + index,
      elo_rating: elo,
      win_count: Math.max(0, 3 - index),
      loss_count: index,
      novelty_score: 4,
      plausibility_score: index === 0 ? 5 : 4,
      testability_score: 4,
      safety_status: 'allow',
      status: 'ranked',
      cluster_id: `cluster-${Math.min(index + 1, 3)}`,
    };
  });

  const evidence: Evidence[] = [
    {
      id: `${run.id}-e1`,
      title: 'Single-cell atlas of disease-relevant regulatory states',
      source: 'PubMed',
      url: 'https://pubmed.ncbi.nlm.nih.gov/',
      authors: ['Reference Team'],
      year: 2024,
      abstract:
        'Maps cellular states and regulatory programs relevant to the target disease context.',
      available: true,
    },
    {
      id: `${run.id}-e2`,
      title: 'Perturbation study of pathway-level reversibility',
      source: 'PubMed',
      url: 'https://pubmed.ncbi.nlm.nih.gov/',
      authors: ['Mechanism Group'],
      year: 2023,
      abstract:
        'Reports measurable reversibility under controlled pathway perturbation.',
      available: true,
    },
    {
      id: `${run.id}-e3`,
      title: 'Human model systems for translational hypothesis testing',
      source: 'PubMed',
      url: 'https://pubmed.ncbi.nlm.nih.gov/',
      authors: ['Translational Consortium'],
      year: 2022,
      abstract:
        'Compares organoid, slice, and single-cell readouts for translational evaluation.',
      available: true,
    },
  ];

  const matches: MatchRow[] = hypotheses.slice(1).map((loser, index) => ({
    id: index + 1,
    iteration: 1,
    winner_id: hypotheses[0].id,
    loser_id: loser.id,
    winner_elo_before: 1200 + index * 20,
    winner_elo_after: hypotheses[0].elo_rating,
    loser_elo_before: 1200,
    loser_elo_after: loser.elo_rating,
    rationale:
      'The winner is more mechanistically specific and easier to test against the stated criteria.',
    tier: ['decisive', 'clear', 'narrow'][index] ?? 'clear',
    created_at: base - 20 + index,
  }));

  const reviews: Review[] = hypotheses.map((hypothesis, index) => ({
    id: index + 1,
    hypothesis_id: hypothesis.id,
    reviewer_agent: 'Review agent',
    summary:
      'Strong mechanistic specificity with an experimentally tractable readout.',
    critique:
      'The hypothesis is promising because it is testable and differentiates itself from broad pathway summaries. The main risk is whether the proposed intermediate state can be isolated cleanly.',
    novelty: hypothesis.novelty_score,
    plausibility: hypothesis.plausibility_score,
    testability: hypothesis.testability_score,
    overall: index === 0 ? 5 : 4,
  }));

  const citations: CitationRow[] = hypotheses.flatMap((hypothesis, hIndex) =>
    evidence.map((item, eIndex) => ({
      id: hIndex * evidence.length + eIndex + 1,
      hypothesis_id: hypothesis.id,
      evidence_id: item.id,
      claim: `${hypothesis.title} is supported by ${item.title}.`,
      state: eIndex === 0 ? 'verified' : 'partial',
    })),
  );

  const report: Report = {
    id: `${run.id}-report`,
    run_id: run.id,
    markdown_path: '',
    created_at: base,
    payload: {
      research_goal: run.research_goal,
      run_mode: 'default',
      profile: 'default',
      provider: 'mock',
      leaderboard: hypotheses.map(h => ({
        id: h.id,
        title: h.title,
        elo: h.elo_rating,
      })),
      citation_summary: {verified: 4, partial: 8},
      evidence_count: evidence.length,
      matches_count: matches.length,
      research_overview: {
        overview: {
          summary: `Synthesizing the top hypotheses for '${run.research_goal}', a coherent research program emerges around ${hypotheses[0].title.toLowerCase()}.`,
          research_directions: [
            {
              title: 'Establish the causal mechanism',
              importance:
                'Confirms the core assumption shared by the top hypotheses.',
              suggested_experiments: [
                'Run a controlled perturbation series with three replicates per condition.',
                'Quantify the readout against baseline and rescue conditions.',
              ],
            },
            {
              title: 'Probe pathway redundancy',
              importance:
                'Tests whether the effect survives compensatory pathway activation.',
              suggested_experiments: [
                'Block the closest compensatory pathway in parallel.',
                'Measure whether the ranked mechanism remains dominant.',
              ],
            },
          ],
        },
        nih_specific_aims: {
          introduction:
            'The top-ranked hypothesis provides a focused path from mechanism to validation.',
          aims: [
            {
              aim: 'Aim 1: Validate the proposed intermediate state.',
              rationale:
                'The intermediate state is the strongest differentiator.',
              approach:
                'Use time-resolved perturbation and orthogonal readouts.',
            },
            {
              aim: 'Aim 2: Establish translational relevance.',
              rationale:
                'Human-relevant validation reduces model-specific risk.',
              approach: 'Repeat the core assay in organoid or slice systems.',
            },
          ],
          impact:
            'A successful result would produce a testable therapeutic direction rather than a literature summary.',
        },
      },
    },
  };

  const events: RunEvent[] = [
    {seq: 1, type: 'supervisor.plan', payload: {}, created_at: base - 55},
    {seq: 2, type: 'literature_review', payload: {}, created_at: base - 45},
    {seq: 3, type: 'generate', payload: {}, created_at: base - 35},
    {seq: 4, type: 'ranking', payload: {}, created_at: base - 25},
    {seq: 5, type: 'report', payload: {}, created_at: base - 5},
  ];

  return {
    run,
    hypotheses,
    evidence,
    matches,
    reviews,
    citations,
    report,
    events,
    safety: [
      {
        stage: 'final',
        decision: 'allow',
        reason: 'No safety issue detected in local mock output.',
        matches: [],
        created_at: base,
      },
    ],
  };
}

export function demoRecords(): OfflineRunRecord[] {
  const base = nowSeconds() - 86400;
  return DEMO_GOALS.map((demo, index) =>
    artifactsFor(
      runFor(demo.id, demo.goal, base - index * 600, {}, 'completed'),
    ),
  );
}
