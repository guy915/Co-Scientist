// Proposed improvements to the AI Co-Scientist architecture, and how they
// relate to each other. This module is the single source of truth for the
// /proposals page and holds content only: no coordinates, colors, or class
// names, so editing the argument stays a pure content edit. Geometry lives
// in proposals_layout.ts and presentation in proposals_graph.tsx.
// Types and edge-kind helpers live in proposals_types.ts and the `edges`
// array in proposals_edges.ts; both are re-exported below so importers keep
// a single entry point.

import type {Cluster, ProposalNode} from './proposals_types';

export type {
  Cluster,
  ClusterId,
  Edge,
  EdgeKind,
  ProposalNode,
} from './proposals_types';
export {EDGE_KINDS, isDirected, leadsFrom} from './proposals_types';
export {edges} from './proposals_edges';

export const clusters: Cluster[] = [
  {id: 'scaling', label: 'Scaling generation'},
  {id: 'evaluation', label: 'Evaluation rigor'},
  {id: 'interaction', label: 'Scientist interaction'},
  {id: 'knowledge', label: 'Knowledge discovery'},
  {id: 'capabilities', label: 'Capabilities'},
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
    featured: true,
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
    id: 'lab-integration',
    label: 'Lab system integration',
    cluster: 'interaction',
    summary:
      'Connect the system to the tools a lab already runs on — electronic ' +
      'notebooks, sample and instrument records, internal databases — so it ' +
      'reads and writes where the work happens.',
    problem:
      'The system sits outside the working environment it is meant to join. ' +
      'Every input is retyped and every output copied back out by hand, and ' +
      "a collaborator who cannot see the lab's own results is reasoning " +
      'about a different project than the one being run.',
    origin: 'extension',
    featured: true,
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
    featured: true,
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
    id: 'full-text-access',
    label: 'Credentialed retrieval',
    cluster: 'knowledge',
    summary:
      "Retrieve through the institution's own subscriptions so the system " +
      'reads the full text its user is already entitled to read.',
    problem:
      'Retrieval reaches only what is openly published, so the system ' +
      'reasons over abstracts while the scientist beside it reads the ' +
      'paper. What it cites is then the evidence that happened to be free, ' +
      'not the evidence that settles the question.',
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

/** Nodes by id. Lookups happen per render, so the index is built once. */
export const nodeById: ReadonlyMap<string, ProposalNode> = new Map(
  nodes.map(node => [node.id, node]),
);
