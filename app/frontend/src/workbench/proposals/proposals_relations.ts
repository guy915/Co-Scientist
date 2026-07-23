// Shared reading of the edge list: how one node's relationships are phrased
// for a human, as shown in the detail panel, and which nodes an edge leads
// to, as lit up in the graph.

import {
  EDGE_KINDS,
  edges,
  leadsFrom,
  nodeById,
  type Edge,
  type EdgeKind,
  type ProposalNode,
} from './proposals_data';

export interface Relation {
  /** The node at the other end. */
  other: ProposalNode;
  kind: EdgeKind;
  note: string;
  /**
   * How to read this edge from the subject's side. Directed edges reverse
   * their phrasing when the subject is the target: `from` is a prerequisite
   * *for* `to`, so from `to`'s side it "depends on" `from`.
   */
  phrase: string;
}

// Directed kinds read differently depending on which end you are standing
// at. Undirected kinds read the same from both sides.
const INBOUND_PHRASE: Partial<Record<EdgeKind, string>> = {
  enables: 'depends on',
  compensates: 'has a weakness mitigated by',
};

// EDGE_KINDS covers every EdgeKind, so this index is total and the lookup
// below cannot miss.
const DEFINITIONS = Object.fromEntries(
  EDGE_KINDS.map(entry => [entry.kind, entry]),
) as Record<EdgeKind, (typeof EDGE_KINDS)[number]>;

function phraseFor(kind: EdgeKind, subjectIsSource: boolean): string {
  const definition = DEFINITIONS[kind];
  if (subjectIsSource || !definition.directed) return definition.phrase;
  return INBOUND_PHRASE[kind] ?? definition.phrase;
}

// One edge translated into `id`'s point of view, or null when the edge does
// not touch `id`.
function relationFor(edge: Edge, id: string): Relation | null {
  const subjectIsSource = edge.from === id;
  if (!subjectIsSource && edge.to !== id) return null;
  const otherId = subjectIsSource ? edge.to : edge.from;
  const other = nodeById.get(otherId);
  if (!other) return null;
  return {
    other,
    kind: edge.kind,
    note: edge.note,
    phrase: phraseFor(edge.kind, subjectIsSource),
  };
}

/**
 * Every relationship touching `id`, phrased from that node's point of view
 * and grouped by kind in legend order.
 *
 * @param id Node whose relationships are wanted.
 * @returns Relations, ordered synergy, enables, compensates, tension.
 */
export function relationsOf(id: string): Relation[] {
  const order = EDGE_KINDS.map(entry => entry.kind);
  const relations = edges
    .map(edge => relationFor(edge, id))
    .filter((relation): relation is Relation => relation !== null);
  return relations.sort(
    (a, b) => order.indexOf(a.kind) - order.indexOf(b.kind),
  );
}

/**
 * Node ids `id` leads to, in no particular order. Incoming arrows are left
 * out: hovering a proposal answers "what does this one carry", not "what
 * points at it".
 */
export function neighborsOf(id: string): Set<string> {
  const found = new Set<string>();
  for (const edge of edges) {
    if (!leadsFrom(edge, id)) continue;
    found.add(edge.from === id ? edge.to : edge.from);
  }
  return found;
}
