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

// Wider than tall, and closer to the shape of the window than a 3:2 canvas
// would be: the graph is fitted with `meet`, so a canvas whose proportions
// disagree with the viewport is letterboxed and everything renders smaller.
export interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}

export const CANVAS: Box = {x: 0, y: 0, width: 1500, height: 800};

/**
 * The two legend cards, in canvas units. They are drawn inside the SVG, so
 * these are real coordinates rather than an estimate of where some HTML
 * happens to land: the clusters can be spaced against them exactly, and the
 * spacing holds at every window size and zoom level.
 *
 * `height` is only the box the card is laid out in; the card itself is as
 * tall as its contents.
 */
export const LEGEND = {
  width: 210,
  height: 340,
  y: 16,
  categories: {x: 16},
  relationships: {x: 1500 - 16 - 210},
};

/** Node box, in canvas units. Labels wrap to at most two lines inside it. */
export const NODE = {width: 178, height: 52};

export interface Point {
  x: number;
  y: number;
}

// The two rows every cluster sits on. Clusters share a row's center line so
// their hulls line up exactly rather than approximately.
//
// The top row sits between the legend cards with an equal gap on each side;
// the bottom row is clear of them and is centered on the canvas.
//
// The two rows are placed together, keeping 55 units between them, so the
// drawing moves as a whole rather than stretching.
const ROW_GAP = 55;

/** Breathing room between a cluster's outermost nodes and its hull. */
const PAD = {x: NODE.width / 2 + 26, y: NODE.height / 2 + 34};

/** Every ring is the same height, which is what equalizes the hulls. */
const RING_RY = 85;

const ROW_HEIGHT = (RING_RY + PAD.y) * 2;

// Centered vertically: equal space above the top row and below the bottom.
const ROWS_TOP = (CANVAS.height - (ROW_HEIGHT * 2 + ROW_GAP)) / 2;
const ROW = {
  top: ROWS_TOP + ROW_HEIGHT / 2,
  bottom: ROWS_TOP + ROW_HEIGHT * 1.5 + ROW_GAP,
};

// Cluster anchors. The top row takes the middle two clusters by width and
// the bottom row the other three, so the narrow row is the one that has to
// fit between the legends.
//
// `rx`/`ry` size the ring the cluster's nodes sit on: wider than tall,
// because node boxes are wide and would otherwise collide left-to-right.
// `start` rotates the ring so the first node lands at the top. Every `ry`
// is equal, which is what makes the hulls share a height.
interface Ring {
  center: Point;
  rx: number;
  ry: number;
  start: number;
}

type Rings = Record<ClusterId, Ring>;

const RINGS: Rings = {
  evaluation: {center: {x: 498, y: ROW.top}, rx: 117, ry: RING_RY, start: -90},
  interaction: {
    center: {x: 1002, y: ROW.top},
    rx: 117,
    ry: RING_RY,
    start: -90,
  },
  capabilities: {
    center: {x: 368, y: ROW.bottom},
    rx: 185,
    ry: RING_RY,
    start: -90,
  },
  knowledge: {center: {x: 814, y: ROW.bottom}, rx: 0, ry: RING_RY, start: -90},
  scaling: {center: {x: 1197, y: ROW.bottom}, rx: 130, ry: RING_RY, start: -90},
};

/**
 * Position of every node, keyed by node id. Nodes are distributed evenly
 * around their cluster's ring in data order, so inserting a node into
 * proposals_data.ts places it without touching this module.
 */
function nodePositionsFor(rings: Rings): Record<string, Point> {
  const positions: Record<string, Point> = {};
  for (const cluster of clusters) {
    const ring = rings[cluster.id];
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
}

export const nodePositions = nodePositionsFor(RINGS);

/**
 * The soft box drawn behind each cluster. Width follows the cluster's own
 * nodes, but height is shared: a row of boxes that differ by twenty pixels
 * reads as a mistake rather than as a difference in content.
 */
function clusterBoundsFor(
  rings: Rings,
  positions: Record<string, Point>,
  clusterId: ClusterId,
) {
  const members = nodes.filter(node => node.cluster === clusterId);
  const xs = members.map(node => positions[node.id].x);
  // The furthest any node sits from its row's center line, so every hull is
  // drawn the same height and the two rows read as rows.
  const halfSpan = Math.max(...Object.values(rings).map(ring => ring.ry));
  const height = (halfSpan + PAD.y) * 2;
  return {
    x: Math.min(...xs) - PAD.x,
    y: rings[clusterId].center.y - height / 2,
    width: Math.max(...xs) - Math.min(...xs) + PAD.x * 2,
    height,
  };
}

export function clusterBounds(clusterId: ClusterId) {
  return clusterBoundsFor(RINGS, nodePositions, clusterId);
}

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
function edgeGeometryFor(positions: Record<string, Point>): EdgeGeometry[] {
  return edges.map((edge, index) => {
    const from = positions[edge.from];
    const to = positions[edge.to];
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
}

export const edgeGeometry = edgeGeometryFor(nodePositions);

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
