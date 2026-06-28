import http from 'node:http';

const now = Math.floor(Date.now() / 1000);
const ferroGoal =
  'What are the key molecular regulators of ferroptosis in pancreatic cancer cells, and how might their modulation enhance chemotherapy sensitivity?';
const autophagyGoal =
  'Identify novel mechanisms of selective autophagy in aging neural tissue.';
const biofilmGoal =
  'What mechanisms drive antibiotic resistance in Staphylococcus aureus biofilms, and which metabolic pathways could be targeted to restore susceptibility?';
const pruningGoal =
  'How does synaptic pruning in the prefrontal cortex contribute to cognitive flexibility during adolescent development?';

const runFerro = {
  id: 'demo-ferroptosis-pancreatic-cancer',
  research_goal: ferroGoal,
  run_mode: 'default',
  profile: 'default',
  status: 'completed',
  provider: 'mock',
  config: {},
  is_demo: true,
  created_at: now - 3600,
  updated_at: now - 1800,
  completed_at: now - 1200,
  error: null,
};

const runBiofilm = {
  ...runFerro,
  id: 'demo-biofilm-antibiotic-resistance',
  research_goal: biofilmGoal,
  created_at: now - 3 * 3600,
  updated_at: now - 2 * 3600,
  completed_at: now - 2 * 3600 + 600,
};

const runPruning = {
  ...runFerro,
  id: 'demo-synaptic-pruning-cognitive-flexibility',
  research_goal: pruningGoal,
  created_at: now - 2 * 3600,
  updated_at: now - 3600,
  completed_at: now - 2400,
};

const runAutophagyCompleted = {
  id: 'legacy-autophagy-completed',
  research_goal: autophagyGoal,
  run_mode: 'default',
  profile: 'default',
  status: 'completed',
  provider: 'engine',
  config: {},
  is_demo: false,
  created_at: now - 15 * 86400,
  updated_at: now - 15 * 86400 + 300,
  completed_at: now - 15 * 86400 + 600,
  error: null,
};

const runAutophagyFailed = {
  ...runAutophagyCompleted,
  id: 'legacy-autophagy-failed',
  status: 'failed',
  completed_at: null,
  error: 'Provider failed before generation.',
};

const hypotheses = [
  [
    'h4-a',
    'H4: Decoupling co-expression in the bottleneck enzyme',
    1257,
    4,
    1,
  ],
  [
    'h4-b',
    'H4: Decoupling co-expression in the bottleneck enzyme',
    1257,
    4,
    1,
  ],
  [
    'h2-a',
    'H2: Perturbing transcriptional control of the upstream regulator',
    1247,
    3,
    0,
  ],
  [
    'h2-b',
    'H2: Perturbing transcriptional control of the upstream regulator',
    1247,
    3,
    0,
  ],
  [
    'h5-a',
    'H5: Rerouting metabolic flux through the dominant pathway',
    1200,
    2,
    1,
  ],
].map(([id, title, elo, wins, losses]) => ({
  id,
  run_id: runFerro.id,
  parent_id: null,
  generation: 0,
  title,
  statement:
    `In the context of '${ferroGoal.split('?')[0]}', we hypothesise that ${String(title)
      .replace(/^H\d+:\s*/, '')
      .toLowerCase()} will produce a measurable effect via a mechanism distinct from current consensus.`,
  mechanism:
    'A regulated pathway shift creates a transient ferroptosis-sensitive state.',
  expected_effect:
    'Increased chemotherapy sensitivity with measurable lipid-peroxidation response.',
  experimental_context:
    'Patient-derived pancreatic cancer organoids and matched stromal co-culture.',
  created_by_agent: 'generation',
  created_at: now - 1700,
  elo_rating: elo,
  win_count: wins,
  loss_count: losses,
  novelty_score: 4,
  plausibility_score: 4,
  testability_score: 5,
  safety_status: 'allow',
  status: 'active',
  cluster_id: null,
}));

const evidence = [
  {
    id: 'ev1',
    title: 'Ferroptosis regulation in pancreatic cancer models',
    source: 'PubMed',
    url: 'https://pubmed.ncbi.nlm.nih.gov/',
    authors: ['Reference Team'],
    year: 2024,
    abstract:
      'Reviews regulatory checkpoints connecting redox state, lipid peroxidation, and chemotherapy response.',
    available: true,
  },
  {
    id: 'ev2',
    title: 'Metabolic dependencies in treatment-resistant tumor states',
    source: 'PubMed',
    url: 'https://pubmed.ncbi.nlm.nih.gov/',
    authors: ['Mechanism Group'],
    year: 2023,
    abstract:
      'Maps candidate metabolic dependencies that may produce conditional treatment sensitivity.',
    available: true,
  },
];

const citations = hypotheses.flatMap(h => [
  {
    id: Number(h.id.replace(/\D/g, '') || 1),
    hypothesis_id: h.id,
    evidence_id: 'ev1',
    claim: 'Regulatory feedback can alter ferroptosis sensitivity.',
    state: 'partial',
  },
  {
    id: Number(h.id.replace(/\D/g, '') || 1) + 100,
    hypothesis_id: h.id,
    evidence_id: 'ev2',
    claim: 'Metabolic state can modulate treatment response.',
    state: 'unsupported',
  },
]);

const reviews = hypotheses.map((h, i) => ({
  id: i + 1,
  hypothesis_id: h.id,
  reviewer_agent: 'critic',
  summary: 'Mechanistically plausible and testable in staged models.',
  critique: 'Needs direct comparison against known ferroptosis regulators.',
  novelty: 4,
  plausibility: 4,
  testability: 5,
  overall: 4,
}));

const matches = [
  {
    id: 1,
    iteration: 1,
    winner_id: 'h4-a',
    loser_id: 'h2-a',
    winner_elo_before: 1200,
    winner_elo_after: 1257,
    loser_elo_before: 1200,
    loser_elo_after: 1247,
    rationale: 'Higher specificity and clearer validation path.',
    created_at: now - 1400,
  },
];

const events = [
  {
    seq: 1,
    type: 'supervisor.plan',
    payload: {agents: ['generate', 'review', 'ranking']},
    created_at: now - 1800,
  },
  {
    seq: 2,
    type: 'literature_review',
    payload: {evidence},
    created_at: now - 1720,
  },
  {
    seq: 3,
    type: 'generate',
    payload: {hypotheses},
    created_at: now - 1660,
  },
  {
    seq: 4,
    type: 'ranking',
    payload: {iteration: 1, matches},
    created_at: now - 1500,
  },
  {
    seq: 5,
    type: 'citation_audit',
    payload: {verified: 0, partial: 5, unsupported: 5, unavailable: 0},
    created_at: now - 1300,
  },
  {
    seq: 6,
    type: 'report',
    payload: {path: '/tmp/report.md'},
    created_at: now - 1000,
  },
];

const report = {
  id: 'report-ferro',
  run_id: runFerro.id,
  payload: {
    research_goal: ferroGoal,
    run_mode: 'default',
    profile: 'default',
    provider: 'mock',
    leaderboard: hypotheses.map(h => ({
      id: h.id,
      title: h.title,
      elo: h.elo_rating,
    })),
    citation_summary: {verified: 0, partial: 5, unsupported: 5, unavailable: 0},
    evidence_count: evidence.length,
    matches_count: matches.length,
    research_overview: {
      overview: {
        summary:
          'The leading hypotheses converge on timed redox and metabolic state changes that may sensitize pancreatic cancer cells to chemotherapy.',
        research_directions: [
          {
            title: 'Timed ferroptosis priming',
            importance: 'Tests whether sequence changes response.',
            suggested_experiments: ['Organoid dose-response', 'Lipid ROS assay'],
          },
        ],
      },
    },
  },
  markdown_path: '/tmp/report.md',
  created_at: now - 1000,
};

function json(res, status, body) {
  res.writeHead(status, {
    'content-type': 'application/json',
    'access-control-allow-origin': '*',
    'access-control-allow-headers': '*',
  });
  res.end(JSON.stringify(body));
}

function notFound(res) {
  json(res, 404, {detail: 'not found'});
}

function withSummary(run) {
  const summary =
    run.is_demo
      ? {
          events: 23,
          hypotheses: hypotheses.length,
          evidence: evidence.length,
          matches: matches.length,
          reviews: reviews.length,
        }
      : {
          events: run.status === 'completed' ? 8 : 2,
          hypotheses: run.status === 'completed' ? 1 : 0,
          evidence: 0,
          matches: 0,
          reviews: 0,
        };
  return {...run, summary};
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://127.0.0.1:8008');
  if (req.method === 'OPTIONS') return json(res, 200, {});
  if (url.pathname === '/health') return json(res, 200, {status: 'ok'});
  if (url.pathname === '/status') {
    return json(res, 200, {
      mcp_available: false,
      pubmed_available: false,
      literature_review_available: false,
      mcp_server_url: '',
      provider: 'engine',
      mock_mode: false,
      has_provider_key: true,
      engine_importable: true,
      model_name: 'deepseek/deepseek-chat',
    });
  }
  if (url.pathname === '/api/runs') {
    return json(res, 200, {runs: [runAutophagyCompleted, runAutophagyFailed]});
  }
  if (url.pathname === '/api/runs/demo') {
    return json(res, 200, {runs: [runFerro, runPruning, runBiofilm]});
  }
  for (const run of [runFerro, runPruning, runBiofilm]) {
    if (url.pathname === `/api/runs/${run.id}`) {
      return json(res, 200, withSummary(run));
    }
  }
  if (url.pathname === `/api/runs/${runAutophagyCompleted.id}`) {
    return json(res, 200, withSummary(runAutophagyCompleted));
  }
  if (url.pathname === `/api/runs/${runAutophagyFailed.id}`) {
    return json(res, 200, withSummary(runAutophagyFailed));
  }
  if (url.pathname.match(/^\/api\/runs\/demo-[^/]+\/hypotheses$/)) {
    return json(res, 200, {hypotheses});
  }
  if (url.pathname.match(/^\/api\/runs\/demo-[^/]+\/evidence$/)) {
    return json(res, 200, {evidence});
  }
  if (url.pathname.match(/^\/api\/runs\/demo-[^/]+\/matches$/)) {
    return json(res, 200, {matches});
  }
  if (url.pathname.match(/^\/api\/runs\/demo-[^/]+\/reviews$/)) {
    return json(res, 200, {reviews});
  }
  if (url.pathname.match(/^\/api\/runs\/demo-[^/]+\/safety$/)) {
    return json(res, 200, {
      safety: [
        {
          stage: 'intake',
          decision: 'allow',
          reason: 'Allowed demo research goal.',
          matches: [],
          created_at: now - 1800,
        },
        {
          stage: 'final',
          decision: 'allow',
          reason: 'Allowed synthesized demonstration output.',
          matches: [],
          created_at: now - 900,
        },
      ],
    });
  }
  if (url.pathname.match(/^\/api\/runs\/demo-[^/]+\/citations$/)) {
    return json(res, 200, {citations});
  }
  if (url.pathname.match(/^\/api\/runs\/demo-[^/]+\/report$/)) {
    return json(res, 200, report);
  }
  if (url.pathname.match(/^\/api\/runs\/demo-[^/]+\/report\.md$/)) {
    res.writeHead(200, {'content-type': 'text/markdown'});
    return res.end(`# Ferroptosis in pancreatic cancer

## Research goal

${ferroGoal}

## Ranked hypotheses

1. **Decoupling co-expression in the bottleneck enzyme** - a timed regulatory split may create a measurable chemotherapy-sensitive state.
2. **Perturbing transcriptional control of the upstream regulator** - upstream transcriptional control may expose a ferroptosis response window.
3. **Rerouting metabolic flux through the dominant pathway** - metabolic dependency may amplify lipid-peroxidation stress during treatment.

## Evidence summary

The demonstration links each hypothesis to mock literature records on ferroptosis regulation, metabolic dependencies, and treatment-resistant tumor states.

## Next experiments

- Compare sequence-first versus simultaneous treatment in patient-derived organoids.
- Measure lipid ROS, cell viability, and pathway-specific rescue markers.
- Validate the strongest hypothesis in stromal co-culture before animal-model escalation.
`);
  }
  if (url.pathname.match(/^\/api\/runs\/demo-[^/]+\/events$/)) {
    res.writeHead(200, {
      'content-type': 'text/event-stream',
      'cache-control': 'no-cache',
      connection: 'keep-alive',
    });
    const replay = [
      ...events,
      {seq: events.length + 1, type: '_terminal', payload: {}},
    ];
    let index = 0;
    const timer = setInterval(() => {
      const event = replay[index++];
      if (!event) {
        clearInterval(timer);
        return res.end();
      }
      res.write(`data: ${JSON.stringify(event)}\n\n`);
      if (event.type === '_terminal') {
        clearInterval(timer);
        return res.end();
      }
    }, 80);
    req.on('close', () => clearInterval(timer));
    return;
  }
  if (url.pathname.match(/^\/api\/runs\/demo-[^/]+\/events\/log$/)) {
    return json(res, 200, events);
  }
  if (url.pathname.endsWith('/messages')) return json(res, 200, {messages: []});
  return notFound(res);
});

server.listen(8008, '127.0.0.1', () => {
  console.log('old co-scientist mock api on http://127.0.0.1:8008');
});
