// Relationship edges for the /proposals graph. Content only, like the rest
// of the proposals data modules; proposals_data.ts re-exports `edges` so
// importers keep a single entry point.

import type {Edge} from './proposals_types';

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
    from: 'lab-integration',
    to: 'experiment-stage',
    kind: 'synergy',
    note:
      'A protocol is worth more when it lands in the notebook the bench ' +
      'already follows, and the notebook is where the result comes back.',
  },
  {
    from: 'lab-integration',
    to: 'persistent-kb',
    kind: 'synergy',
    note:
      "The lab's own unpublished results are the entries no public corpus " +
      'holds, and the ones it most wants to keep.',
  },
  {
    from: 'lab-integration',
    to: 'full-text-access',
    kind: 'synergy',
    note:
      'Both are the same boundary from opposite sides: one reaches the ' +
      "lab's private data, the other the literature's gated half.",
  },
  {
    from: 'full-text-access',
    to: 'persistent-kb',
    kind: 'synergy',
    note:
      'A knowledge base built from abstracts stores summaries of evidence ' +
      'rather than evidence.',
  },
  {
    from: 'full-text-access',
    to: 'multimodal',
    kind: 'synergy',
    note:
      'Figures, tables and methods sit in the full text; without it there ' +
      'is little left to parse.',
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
    from: 'lab-integration',
    to: 'data-requests',
    kind: 'compensates',
    note:
      'Asking the scientist to fetch a number by hand is the fallback for ' +
      'a system that cannot read the instrument itself.',
  },
  {
    from: 'full-text-access',
    to: 'transitivity',
    kind: 'compensates',
    note:
      'A link stated in a results section but absent from the abstract is ' +
      'exactly the link a transitive search exists to find.',
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
    from: 'brute-force',
    to: 'full-text-access',
    kind: 'tension',
    note:
      'Publisher access is metered per request, so a large population ' +
      'cannot each pull the papers behind it.',
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
