// Proposed improvements to the AI Co-Scientist architecture, and how they
// relate to each other. This module is the single source of truth for the
// /proposals page and holds content only: no coordinates, colors, or class
// names, so editing the argument stays a pure content edit. Geometry lives
// in proposals_layout.ts and presentation in proposals_graph.tsx.

export type ClusterId =
  | 'scaling'
  | 'evaluation'
  | 'interaction'
  | 'knowledge'
  | 'capabilities';

export type EdgeKind = 'synergy' | 'enables' | 'compensates' | 'tension';

export interface Cluster {
  id: ClusterId;
  label: string;
  blurb: string;
}

export interface ProposalNode {
  id: string;
  /** Short label, rendered inside the node. */
  label: string;
  cluster: ClusterId;
  /** The proposal itself. */
  summary: string;
  /** The weakness it addresses. */
  problem: string;
  /** Citation into the Co-Scientist paper, where one applies. */
  source?: string;
  /**
   * Whether this fixes something the paper does ('critique') or adds
   * something the paper has no analogue for ('extension').
   */
  origin: 'critique' | 'extension';
}

export interface Edge {
  from: string;
  to: string;
  kind: EdgeKind;
  /** Why this relationship exists. */
  note: string;
}

/**
 * Edge semantics, used by the legend and the prose rendering. `directed`
 * drives the arrowhead: undirected kinds describe a mutual relationship, so
 * from/to carry no meaning beyond authoring order.
 */
export const EDGE_KINDS: {
  kind: EdgeKind;
  label: string;
  directed: boolean;
  /** Reads as "<from> <phrase> <to>" in the prose rendering. */
  phrase: string;
  blurb: string;
}[] = [
  {
    kind: 'synergy',
    label: 'Synergy',
    directed: false,
    phrase: 'amplifies and is amplified by',
    blurb: 'Mutually amplifying. Each is worth more with the other.',
  },
  {
    kind: 'enables',
    label: 'Enables',
    directed: true,
    phrase: 'is a prerequisite for',
    blurb: 'A hard prerequisite. The target does not function without it.',
  },
  {
    kind: 'compensates',
    label: 'Compensates',
    directed: true,
    phrase: 'mitigates a weakness of',
    blurb: 'Mitigates a known weakness of the target.',
  },
  {
    kind: 'tension',
    label: 'Tension',
    directed: false,
    phrase: 'competes with',
    blurb: 'They compete for the same budget, or one makes the other harder.',
  },
];

export const clusters: Cluster[] = [
  {
    id: 'scaling',
    label: 'Scaling generation',
    blurb: 'Widening the hypothesis space explored before filtering starts.',
  },
  {
    id: 'evaluation',
    label: 'Evaluation rigor',
    blurb: 'Making survival mean something worth surviving.',
  },
  {
    id: 'interaction',
    label: 'Scientist interaction',
    blurb: 'Turning a fire-and-forget batch job into a working session.',
  },
  {
    id: 'knowledge',
    label: 'Knowledge and discovery',
    blurb:
      'Keeping what a run learns, and mining it for connections nobody ' +
      'asked about.',
  },
  {
    id: 'capabilities',
    label: 'Capabilities',
    blurb: 'Extending what the system can reason over and produce.',
  },
];

export const nodes: ProposalNode[] = [
  {
    id: 'brute-force',
    label: 'Brute-force generation',
    cluster: 'scaling',
    summary:
      'Generate hypotheses at high volume and let the tournament do the ' +
      'filtering.',
    problem:
      'The paper dismisses generating at volume, but inference is cheap ' +
      'and a ranking mechanism already exists. The constraint it assumes ' +
      'no longer binds.',
    source: 'p. 31',
    origin: 'critique',
  },
  {
    id: 'embedding-proximity',
    label: 'Embedding proximity',
    cluster: 'scaling',
    summary:
      'Replace the LLM-based Proximity agent with vector similarity for ' +
      'clustering and deduplication.',
    problem:
      'Pairwise LLM similarity calls scale quadratically with population ' +
      'size, capping how many hypotheses the system can hold at once.',
    origin: 'critique',
  },
  {
    id: 'temperature',
    label: 'Temperature tuning',
    cluster: 'scaling',
    summary:
      'Raise sampling temperature in the Generation agent to push toward ' +
      'divergent hypotheses.',
    problem:
      'Default sampling clusters around the consensus reading of the ' +
      'literature, which is the region least likely to contain a novel ' +
      'hypothesis.',
    origin: 'critique',
  },
  {
    id: 'adversary',
    label: 'Adversary agent',
    cluster: 'evaluation',
    summary:
      'A dedicated agent that attacks surviving hypotheses by searching ' +
      'for disconfirming evidence.',
    problem:
      'The scientific method turns on failure to disprove, not ' +
      'accumulation of support. No role in the coalition has killing a ' +
      'hypothesis as its objective.',
    origin: 'extension',
  },
  {
    id: 'granular-scoring',
    label: '1-10 scoring',
    cluster: 'evaluation',
    summary: 'Widen internal review scoring from a 1-5 scale to 1-10.',
    problem:
      'A 1-5 scale collapses genuinely different hypotheses onto the same ' +
      'value, making downstream filtering arbitrary.',
    source: '§4.5.1',
    origin: 'critique',
  },
  {
    id: 'multi-dim-ranking',
    label: 'Multi-dimensional ranking',
    cluster: 'evaluation',
    summary:
      'Present hypotheses as a scored matrix across several axes instead ' +
      'of a single Elo leaderboard.',
    problem:
      'One Elo number hides why a hypothesis ranks where it does, making ' +
      'the ranking impossible to audit or disagree with.',
    source: 'Fig. 6, p. 17',
    origin: 'critique',
  },
  {
    id: 'review-consolidation',
    label: 'Review consolidation',
    cluster: 'evaluation',
    summary:
      'Merge the six Reflection review types into fewer, better-prompted ' +
      'passes.',
    problem:
      'Observation review frequently returns nothing, which the paper ' +
      'acknowledges. Six passes per hypothesis is a fixed cost paid ' +
      'whether or not each earns its place.',
    source: 'p. 11',
    origin: 'critique',
  },
  {
    id: 'live-session',
    label: 'Live sessions',
    cluster: 'interaction',
    summary:
      'Keep the run conversational and interruptible instead of ' +
      'fire-and-forget.',
    problem:
      'The paper claims expert-in-the-loop, but the system launches from ' +
      'a single prompt and runs to completion asynchronously. The expert ' +
      'is in the loop exactly once.',
    source: 'p. 4',
    origin: 'critique',
  },
  {
    id: 'hypothesis-injection',
    label: 'Hypothesis injection',
    cluster: 'interaction',
    summary:
      'Let the scientist enter their own hypotheses into the tournament ' +
      'mid-run.',
    problem:
      'The paper supports this in principle but leaves the interaction ' +
      "undefined, so in practice the scientist's own ideas never compete.",
    source: '§3.4',
    origin: 'critique',
  },
  {
    id: 'data-requests',
    label: 'Data requests',
    cluster: 'interaction',
    summary:
      'Let the system ask the scientist for specific experimental data ' +
      'and fold the answer back into evolution.',
    problem:
      'The system can only reason over what already exists in the ' +
      'literature, so it stalls exactly where the literature is thin — ' +
      'which is where the interesting questions are.',
    origin: 'extension',
  },
  {
    id: 'question-generation',
    label: 'Question generation',
    cluster: 'interaction',
    summary:
      'Apply the same generate-critique-rank loop to the research ' +
      'question itself.',
    problem:
      'The system assumes the research goal is given and correct. ' +
      'Choosing the right question is frequently harder than answering it.',
    origin: 'extension',
  },
  {
    id: 'persistent-kb',
    label: 'Persistent knowledge base',
    cluster: 'knowledge',
    summary:
      'Write everything a run reads into an exportable structured wiki ' +
      'that outlives the run.',
    problem:
      'A run performs a broad literature review and then discards it. The ' +
      'next run on an adjacent topic starts from nothing.',
    origin: 'extension',
  },
  {
    id: 'transitivity',
    label: 'Transitivity flagging',
    cluster: 'knowledge',
    summary:
      'Flag A-C when A links to B and B links to C but A and C never ' +
      'co-occur in the literature.',
    problem:
      'Undiscovered public knowledge is exactly what a comprehensive ' +
      'review surfaces incidentally and then drops, because no agent is ' +
      'looking for it.',
    origin: 'extension',
  },
  {
    id: 'experiment-stage',
    label: 'Experiment protocols',
    cluster: 'capabilities',
    summary:
      'A dedicated stage after ranking that turns a hypothesis into a ' +
      'bench-ready protocol.',
    problem:
      'The paper claims to provide experimental protocols, but the ' +
      'examples are high-level outlines — assay classes and concentration ' +
      'ranges, not something a postdoc can run.',
    source: 'p. 4',
    origin: 'critique',
  },
  {
    id: 'bio-simulation',
    label: 'Bio simulation tools',
    cluster: 'capabilities',
    summary:
      'Give agents tool access to domain models for structure and ' +
      'interaction prediction.',
    problem:
      'Hypotheses about physical systems are evaluated purely on textual ' +
      'plausibility, with no check against the models that could falsify ' +
      'them cheaply.',
    source: 'App. A.6',
    origin: 'critique',
  },
  {
    id: 'multimodal',
    label: 'Multimodal I/O',
    cluster: 'capabilities',
    summary:
      'Parse papers into markdown with figures extracted and captioned, ' +
      'and produce structured visual output.',
    problem:
      'The paper flags weak reasoning over figures and charts. A large ' +
      "share of a paper's actual evidence lives in its figures, and " +
      'text-only ingestion discards it.',
    source: 'p. 27',
    origin: 'critique',
  },
  {
    id: 'model-fusion',
    label: 'Model fusion',
    cluster: 'capabilities',
    summary:
      'A unified API layer that routes different agent roles to different ' +
      'underlying models.',
    problem:
      'A single model imposes one set of blind spots on every role in the ' +
      'coalition, which is the opposite of how a research team works.',
    origin: 'extension',
  },
  {
    id: 'unreinforced-eval',
    label: 'Unreinforced model eval',
    cluster: 'capabilities',
    summary: 'Evaluate the pipeline on non-RL-tuned base models.',
    problem:
      'It is unclear how much of the output quality comes from the agent ' +
      'architecture and how much from RLHF-induced answer shaping in the ' +
      'underlying model.',
    origin: 'extension',
  },
];

// A pair may carry two edges of different kinds — persistent-kb/transitivity
// has both an `enables` and a `compensates`, in opposite directions, and both
// are true. Nothing here deduplicates by node pair.
export const edges: Edge[] = [
  {
    from: 'brute-force',
    to: 'embedding-proximity',
    kind: 'synergy',
    note:
      'Volume is what makes dedup necessary; cheap dedup is what makes ' +
      'volume affordable.',
  },
  {
    from: 'brute-force',
    to: 'temperature',
    kind: 'synergy',
    note: 'Volume without divergence samples the same region repeatedly.',
  },
  {
    from: 'temperature',
    to: 'embedding-proximity',
    kind: 'synergy',
    note:
      'High temperature raises the near-duplicate and outlier rate that ' +
      'clustering absorbs.',
  },
  {
    from: 'adversary',
    to: 'multi-dim-ranking',
    kind: 'synergy',
    note:
      'Survivability under attack is a ranking axis a single Elo score ' +
      'cannot express.',
  },
  {
    from: 'granular-scoring',
    to: 'multi-dim-ranking',
    kind: 'synergy',
    note:
      'A matrix view needs resolution per axis; a 1-5 scale collapses ' +
      'cells that should differ.',
  },
  {
    from: 'embedding-proximity',
    to: 'multi-dim-ranking',
    kind: 'synergy',
    note:
      'Embedding distance from the population gives a novelty axis for ' +
      'free.',
  },
  {
    from: 'hypothesis-injection',
    to: 'multi-dim-ranking',
    kind: 'synergy',
    note:
      "Per-axis scores show where a scientist's hypothesis beats the " +
      "machine's, which one Elo number hides.",
  },
  {
    from: 'data-requests',
    to: 'experiment-stage',
    kind: 'synergy',
    note:
      'A concrete protocol is what tells the system which data is worth ' +
      'asking for.',
  },
  {
    from: 'bio-simulation',
    to: 'experiment-stage',
    kind: 'synergy',
    note:
      'Simulation screens protocols in silico before anyone pays bench ' +
      'cost.',
  },
  {
    from: 'multimodal',
    to: 'persistent-kb',
    kind: 'synergy',
    note:
      'Extracted figures and captions are the highest-value entries the ' +
      'knowledge base can hold.',
  },
  {
    from: 'multimodal',
    to: 'bio-simulation',
    kind: 'synergy',
    note:
      'Simulation output is structures and curves; text-only rendering ' +
      'throws away the result.',
  },
  {
    from: 'live-session',
    to: 'hypothesis-injection',
    kind: 'enables',
    note: 'Injection requires a run that accepts input after it has started.',
  },
  {
    from: 'live-session',
    to: 'data-requests',
    kind: 'enables',
    note:
      'The system needs an open channel to ask a question and receive an ' +
      'answer.',
  },
  {
    from: 'live-session',
    to: 'question-generation',
    kind: 'enables',
    note:
      'Refining the question is a negotiation, and a batch job cannot ' +
      'negotiate.',
  },
  {
    from: 'persistent-kb',
    to: 'transitivity',
    kind: 'enables',
    note:
      'Transitive links can only be computed over a graph that outlives a ' +
      'single run.',
  },
  {
    from: 'model-fusion',
    to: 'unreinforced-eval',
    kind: 'enables',
    note:
      'Swapping the model per role is the harness that makes base-model ' +
      'evaluation practical.',
  },
  {
    from: 'embedding-proximity',
    to: 'brute-force',
    kind: 'compensates',
    note:
      "Redundancy is brute-force's dominant cost, and clustering " +
      'collapses it.',
  },
  {
    from: 'adversary',
    to: 'brute-force',
    kind: 'compensates',
    note:
      'Volume inflates the count of plausible-but-unfalsifiable ' +
      'hypotheses; the adversary culls them.',
  },
  {
    from: 'review-consolidation',
    to: 'brute-force',
    kind: 'compensates',
    note:
      'Six review passes per hypothesis is the wall volume hits first; ' +
      'fewer passes moves the wall.',
  },
  {
    from: 'granular-scoring',
    to: 'review-consolidation',
    kind: 'compensates',
    note:
      'Fewer passes means each score carries more weight, so each score ' +
      'needs more resolution.',
  },
  {
    from: 'transitivity',
    to: 'persistent-kb',
    kind: 'compensates',
    note:
      'Without something mining it, the knowledge base is an archive ' +
      'nobody reads.',
  },
  {
    from: 'adversary',
    to: 'review-consolidation',
    kind: 'tension',
    note:
      'One adds a seventh review type while the other exists to remove ' +
      'review types.',
  },
  {
    from: 'brute-force',
    to: 'adversary',
    kind: 'tension',
    note:
      'Adversarial review is expensive per hypothesis and cannot run on ' +
      'the full population without a gate.',
  },
  {
    from: 'brute-force',
    to: 'live-session',
    kind: 'tension',
    note:
      'A long asynchronous batch run is the opposite of a responsive ' +
      'session.',
  },
  {
    from: 'brute-force',
    to: 'bio-simulation',
    kind: 'tension',
    note:
      'Simulation cost per hypothesis forbids running it across a large ' +
      'population.',
  },
  {
    from: 'brute-force',
    to: 'experiment-stage',
    kind: 'tension',
    note:
      'Protocol generation is expensive and only makes sense for the top ' +
      'of the ranking.',
  },
  {
    from: 'temperature',
    to: 'adversary',
    kind: 'tension',
    note:
      "Higher temperature raises the adversary's kill rate, so compute is " +
      'spent generating and then refuting.',
  },
  {
    from: 'model-fusion',
    to: 'granular-scoring',
    kind: 'tension',
    note:
      'Models calibrate a 1-10 scale differently, so cross-model scores ' +
      'are not comparable without normalization.',
  },
];

/** Page copy. Kept here so the whole page is one content edit. */
export const PAGE_COPY = {
  title: 'Proposals',
  standfirst:
    'Eighteen proposed improvements to the AI Co-Scientist architecture, ' +
    'and how they interact.',
  intro:
    'Anyone can list eighteen feature ideas. The argument here is in the ' +
    'edges: some of these are only viable together, some cancel each ' +
    'other out, and one — brute-force generation — is at once the ' +
    'highest-leverage and highest-risk proposal, because most of the ' +
    'tension in the system routes through it.',
  graphHint:
    'Hover a proposal to isolate its relationships, or select one to read ' +
    'them.',
};
