// Deterministic geometry for the proposals graph. Positions are computed
// from fixed per-cluster rings rather than a force simulation, so the same
// data always lays out identically on every machine and a selected node can
// be linked to. Content lives in proposals_data.ts; colors live in CSS.

import {
  clusters,
  edges,
  leadsFrom,
  nodes,
  type ClusterId,
  type Edge,
} from './proposals_data';

export const CANVAS = {width: 1200, height: 800};

/** Node box, in canvas units. Labels wrap to at most two lines inside it. */
export const NODE = {width: 152, height: 44};

export interface Point {
  x: number;
  y: number;
}

// Cluster anchors, hand-placed so that the clusters with the most traffic
// between them sit adjacent and long edges stay rare. `rx`/`ry` size the
// ring the cluster's nodes sit on: wider than tall, because node boxes are
// wide and would otherwise collide left-to-right. `start` rotates the ring
// so the first node lands at the top.
const RINGS: Record<
  ClusterId,
  {center: Point; rx: number; ry: number; start: number}
> = {
  scaling: {center: {x: 250, y: 325}, rx: 110, ry: 95, start: -90},
  evaluation: {center: {x: 625, y: 155}, rx: 125, ry: 100, start: -90},
  interaction: {center: {x: 305, y: 630}, rx: 125, ry: 100, start: -90},
  knowledge: {center: {x: 1000, y: 190}, rx: 0, ry: 78, start: -90},
  capabilities: {center: {x: 830, y: 520}, rx: 160, ry: 100, start: -90},
};

export const clusterCenters: Record<ClusterId, Point> = {
  scaling: RINGS.scaling.center,
  evaluation: RINGS.evaluation.center,
  interaction: RINGS.interaction.center,
  knowledge: RINGS.knowledge.center,
  capabilities: RINGS.capabilities.center,
};

/**
 * Position of every node, keyed by node id. Nodes are distributed evenly
 * around their cluster's ring in data order, so inserting a node into
 * proposals_data.ts places it without touching this module.
 */
export const nodePositions: Record<string, Point> = (() => {
  const positions: Record<string, Point> = {};
  for (const cluster of clusters) {
    const ring = RINGS[cluster.id];
    const members = nodes.filter(node => node.cluster === cluster.id);
    members.forEach((node, index) => {
      const step = 360 / members.length;
      const radians = ((ring.start + index * step) * Math.PI) / 180;
      positions[node.id] = {
        x: ring.center.x + Math.cos(radians) * ring.rx,
        y: ring.center.y + Math.sin(radians) * ring.ry,
      };
    });
  }
  return positions;
})();

/** Stable key for an unordered node pair. */
function pairKey(edge: Edge): string {
  return [edge.from, edge.to].sort().join('~');
}

/**
 * Perpendicular offset for each edge, so that two edges between the same
 * pair of nodes (persistent-kb/transitivity carries both an `enables` and a
 * `compensates`) bow apart instead of drawing on top of each other.
 */
const edgeOffsets: number[] = (() => {
  const counts = new Map<string, number>();
  for (const edge of edges) {
    counts.set(pairKey(edge), (counts.get(pairKey(edge)) ?? 0) + 1);
  }
  const seen = new Map<string, number>();
  return edges.map(edge => {
    const key = pairKey(edge);
    const total = counts.get(key) ?? 1;
    const index = seen.get(key) ?? 0;
    seen.set(key, index + 1);
    if (total === 1) return 0;
    return (index - (total - 1) / 2) * 42;
  });
})();

/**
 * Where a line aimed at a box's center crosses the box edge. Endpoints stop
 * at the boundary so an arrowhead reads as pointing at the node rather than
 * disappearing beneath it.
 */
function boundaryPoint(box: Point, toward: Point, pad: number): Point {
  const dx = toward.x - box.x;
  const dy = toward.y - box.y;
  if (dx === 0 && dy === 0) return box;
  const halfWidth = NODE.width / 2 + pad;
  const halfHeight = NODE.height / 2 + pad;
  // Scale the direction vector until it first touches a side, then take
  // whichever side it reaches first.
  const scale = Math.min(
    dx === 0 ? Infinity : halfWidth / Math.abs(dx),
    dy === 0 ? Infinity : halfHeight / Math.abs(dy),
  );
  return {x: box.x + dx * scale, y: box.y + dy * scale};
}

export interface EdgeGeometry {
  edge: Edge;
  /** SVG path data: a straight line, or a quadratic curve when offset. */
  path: string;
  /** Midpoint of the drawn curve, for hit-testing and labels. */
  mid: Point;
}

/**
 * Path geometry for every edge, in the same order as `edges`.
 */
export const edgeGeometry: EdgeGeometry[] = edges.map((edge, index) => {
  const from = nodePositions[edge.from];
  const to = nodePositions[edge.to];
  const offset = edgeOffsets[index];

  // Control point sits perpendicular to the midpoint, bowing the curve away
  // from any sibling edge sharing the same pair.
  const midX = (from.x + to.x) / 2;
  const midY = (from.y + to.y) / 2;
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const length = Math.hypot(dx, dy) || 1;
  const control: Point = {
    x: midX + (-dy / length) * offset,
    y: midY + (dx / length) * offset,
  };

  // Trim both ends to the node boundary, aiming at the control point so
  // curved edges leave and arrive at sensible angles.
  const start = boundaryPoint(from, offset === 0 ? to : control, 4);
  const end = boundaryPoint(to, offset === 0 ? from : control, 8);

  const path =
    offset === 0
      ? `M ${start.x} ${start.y} L ${end.x} ${end.y}`
      : `M ${start.x} ${start.y} Q ${control.x} ${control.y} ${end.x} ${end.y}`;

  return {
    edge,
    path,
    mid: {
      x: (start.x + end.x) / 2 + (-dy / length) * offset * 0.5,
      y: (start.y + end.y) / 2 + (dx / length) * offset * 0.5,
    },
  };
});

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

/** Every edge touching `id`. */
export function edgesOf(id: string): Edge[] {
  return edges.filter(edge => edge.from === id || edge.to === id);
}
