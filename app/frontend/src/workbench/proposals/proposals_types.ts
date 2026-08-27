// Shared types, edge-kind metadata, and edge-direction helpers for the
// /proposals content modules. Split out of proposals_data.ts (which
// re-exports everything here) so both proposals_data.ts and
// proposals_edges.ts can use the types without a require cycle.

export type ClusterId =
  'scaling' | 'evaluation' | 'interaction' | 'knowledge' | 'capabilities';

export type EdgeKind = 'synergy' | 'enables' | 'compensates' | 'tension';

export interface Cluster {
  id: ClusterId;
  label: string;
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
  /** Marked with a star in the graph as one of a small hand-picked set. */
  featured?: boolean;
}

export interface Edge {
  from: string;
  to: string;
  kind: EdgeKind;
  /** Why this relationship exists. */
  note: string;
}

/**
 * Edge semantics, used by the legend and the detail panel. `directed`
 * drives the arrowhead: undirected kinds describe a mutual relationship, so
 * from/to carry no meaning beyond authoring order.
 */
export const EDGE_KINDS: {
  kind: EdgeKind;
  label: string;
  directed: boolean;
  /** Reads as "<from> <phrase> <to>" in the detail panel. */
  phrase: string;
}[] = [
  {
    kind: 'synergy',
    label: 'Synergy',
    directed: false,
    phrase: 'amplifies and is amplified by',
  },
  {
    kind: 'enables',
    label: 'Enables',
    directed: true,
    phrase: 'is a prerequisite for',
  },
  {
    kind: 'compensates',
    label: 'Compensates',
    directed: true,
    phrase: 'mitigates a weakness of',
  },
  {
    kind: 'tension',
    label: 'Tension',
    directed: false,
    phrase: 'competes with',
  },
];

const DIRECTED = new Set<EdgeKind>(
  EDGE_KINDS.filter(entry => entry.directed).map(entry => entry.kind),
);

/** Whether `kind` draws an arrowhead: its from/to order carries meaning. */
export function isDirected(kind: EdgeKind): boolean {
  return DIRECTED.has(kind);
}

/**
 * Whether an edge leads away from `id`. A directed edge does so only from
 * its source; an undirected one has no source, so either endpoint leads
 * away along it.
 */
export function leadsFrom(edge: Edge, id: string): boolean {
  if (edge.from === id) return true;
  return edge.to === id && !DIRECTED.has(edge.kind);
}
