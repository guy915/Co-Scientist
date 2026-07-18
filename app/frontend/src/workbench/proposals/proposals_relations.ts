// Shared reading of the edge list: how one node's relationships are phrased
// for a human. Used by both the detail panel and the prose rendering, so the
// two cannot describe the same edge differently.

import {
  EDGE_KINDS,
  edges,
  nodes,
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

const byId = new Map(nodes.map(node => [node.id, node]));

// Directed kinds read differently depending on which end you are standing
// at. Undirected kinds read the same from both sides.
const INBOUND_PHRASE: Partial<Record<EdgeKind, string>> = {
  enables: 'depends on',
  compensates: 'has a weakness mitigated by',
};

function phraseFor(kind: EdgeKind, subjectIsSource: boolean): string {
  const definition = EDGE_KINDS.find(entry => entry.kind === kind);
  if (!definition) return 'relates to';
  if (subjectIsSource || !definition.directed) return definition.phrase;
  return INBOUND_PHRASE[kind] ?? definition.phrase;
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
  const relations: Relation[] = [];
  for (const edge of edges) {
    const subjectIsSource = edge.from === id;
    if (!subjectIsSource && edge.to !== id) continue;
    const otherId = subjectIsSource ? edge.to : edge.from;
    const other = byId.get(otherId);
    if (!other) continue;
    relations.push({
      other,
      kind: edge.kind,
      note: edge.note,
      phrase: phraseFor(edge.kind, subjectIsSource),
    });
  }
  return relations.sort(
    (a, b) => order.indexOf(a.kind) - order.indexOf(b.kind),
  );
}

/** Count of edges touching `id`, counting both edges of a doubled pair. */
export function degreeOf(id: string): number {
  return edges.filter((edge: Edge) => edge.from === id || edge.to === id)
    .length;
}
