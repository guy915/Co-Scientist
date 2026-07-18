// Geometry for the proposals graph, computed from the space it is given.
//
// Everything here is in CSS pixels and is laid out 1:1 — the drawing is never
// scaled to fit. Resizing the window re-runs the layout so the clusters
// re-flow, and zooming behaves the way it does anywhere else on the page:
// every element, the legends included, changes by the same amount. A fitted
// viewBox would instead shrink the drawing while leaving fixed-size siblings
// alone, which is what made the legends drift against the clusters.
//
// Content lives in proposals_data.ts; colors live in CSS.

import {
  clusters,
  edges,
  leadsFrom,
  nodes,
  type ClusterId,
  type Edge,
} from './proposals_data';

/** Node box. Labels wrap to at most two lines inside it. */
export const NODE = {width: 186, height: 54};

/** One spacing value, used between clusters and around the rows. */
const GAP = 40;

/** Space between the two rows. */
const ROW_GAP = 48;

/** Breathing room between a cluster's outermost nodes and its hull. */
const PAD = {x: NODE.width / 2 + 26, y: NODE.height / 2 + 32};

/** Smallest empty space allowed between two node boxes. */
const CLEAR = 26;

/** Ring half-height, clamped so tall or short windows stay sensible. */
const RY = {min: 66, max: 104};

/** Used when the container has not been measured yet (tests, first paint). */
const FALLBACK = {width: 1440, height: 760};

// Which row each cluster sits on, left to right. The top row is the one that
// has to share its line with the legends, so it holds the two clusters that
// need the least width.
const TOP_ROW: ClusterId[] = ['evaluation', 'interaction'];
const BOTTOM_ROW: ClusterId[] = ['capabilities', 'knowledge', 'scaling'];

export interface Point {
  x: number;
  y: number;
}

export interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface EdgeGeometry {
  edge: Edge;
  /** SVG path data: a straight line, or a quadratic curve when offset. */
  path: string;
}

export interface Layout {
  width: number;
  height: number;
  positions: Record<string, Point>;
  hulls: {id: ClusterId; label: string; bounds: Box}[];
  edges: EdgeGeometry[];
}

/** The space the graph has to work with, in CSS pixels. */
export interface Stage {
  width: number;
  height: number;
  /** Width of each legend card, or 0 when it is not shown. */
  legendLeft: number;
  legendRight: number;
}

/** Angles, in radians, of a ring of `count` nodes starting at the top. */
function ringAngles(count: number): number[] {
  return Array.from(
    {length: count},
    (_, index) => ((-90 + (index * 360) / count) * Math.PI) / 180,
  );
}

/**
 * How many multiples of `rx` a ring of `count` nodes spans horizontally.
 * Derived rather than tabulated, so adding a proposal cannot invalidate it.
 */
function extentFactor(count: number): number {
  const cosines = ringAngles(count).map(Math.cos);
  return Math.max(...cosines) - Math.min(...cosines);
}

/**
 * The smallest `rx` at which no two nodes in the ring overlap. Two nodes are
 * clear of each other if either axis separates them, so only the pairs that
 * fail vertically constrain the horizontal radius.
 */
function minimumRx(count: number, ry: number): number {
  const angles = ringAngles(count);
  let required = 0;
  for (let i = 0; i < count; i++) {
    for (let j = i + 1; j < count; j++) {
      const dSin = Math.abs(Math.sin(angles[i]) - Math.sin(angles[j]));
      if (dSin * ry - NODE.height >= CLEAR) continue;
      const dCos = Math.abs(Math.cos(angles[i]) - Math.cos(angles[j]));
      if (dCos < 1e-6) continue;
      required = Math.max(required, (NODE.width + CLEAR) / dCos);
    }
  }
  return required;
}

function memberIds(clusterId: ClusterId): string[] {
  return nodes.filter(node => node.cluster === clusterId).map(node => node.id);
}

/** Hull width for a cluster whose ring has the given radius. */
function hullWidth(clusterId: ClusterId, rx: number): number {
  return extentFactor(memberIds(clusterId).length) * rx + PAD.x * 2;
}

/** The ring radius below which a row's nodes would start overlapping. */
function minimumRowRadius(row: ClusterId[], ry: number): number {
  return Math.max(...row.map(id => minimumRx(memberIds(id).length, ry)));
}

/**
 * The ring radius that makes a row of clusters fill `available`, never
 * smaller than the radius each cluster needs to keep its nodes apart.
 */
function rowRadius(row: ClusterId[], available: number, ry: number): number {
  const factors = row.reduce(
    (total, id) => total + extentFactor(memberIds(id).length),
    0,
  );
  const forNodes = available - PAD.x * 2 * row.length;
  const fitted = factors > 0 ? forNodes / factors : 0;
  return Math.max(fitted, minimumRowRadius(row, ry));
}

/** Width a row occupies at `rx`, including the gaps around and between it. */
function rowWidth(row: ClusterId[], rx: number, reserved: number): number {
  const hulls = row.reduce((total, id) => total + hullWidth(id, rx), 0);
  return hulls + GAP * (row.length + 1) + reserved;
}

/** Ring centers for one row, laid left to right from `start`. */
function placeRow(
  row: ClusterId[],
  rx: number,
  start: number,
  y: number,
): Record<string, {center: Point; rx: number}> {
  const placed: Record<string, {center: Point; rx: number}> = {};
  let x = start;
  for (const id of row) {
    const width = hullWidth(id, rx);
    placed[id] = {center: {x: x + width / 2, y}, rx};
    x += width + GAP;
  }
  return placed;
}

/**
 * Lay the whole graph out inside `stage`.
 *
 * The top row is placed between the legend cards with an equal gap on each
 * side and between its clusters; the bottom row runs the full width. Both
 * rows are sized from the space left over, so the drawing fills the stage
 * rather than being scaled into it.
 */
export function computeLayout(stage: Stage): Layout {
  const width = stage.width || FALLBACK.width;
  const height = stage.height || FALLBACK.height;

  const rowHeight = (height - ROW_GAP) / 2;
  const ry = Math.min(RY.max, Math.max(RY.min, rowHeight / 2 - PAD.y));
  const hullHeight = (ry + PAD.y) * 2;
  const top = Math.max(0, (height - (hullHeight * 2 + ROW_GAP)) / 2);

  // The top row shares its line with the legends: one gap to the left card,
  // one between the clusters, one to the right card.
  const reserved = stage.legendLeft + stage.legendRight;

  // Below a certain width the clusters cannot shrink any further without
  // their own nodes colliding, so the drawing claims the width it needs and
  // the stage scrolls. Overlapping the legends instead would hide content.
  const floors = {
    top: minimumRowRadius(TOP_ROW, ry),
    bottom: minimumRowRadius(BOTTOM_ROW, ry),
  };
  const needed = Math.max(
    rowWidth(TOP_ROW, floors.top, reserved),
    rowWidth(BOTTOM_ROW, floors.bottom, 0),
  );
  const canvasWidth = Math.max(width, needed);

  const topRx = rowRadius(
    TOP_ROW,
    canvasWidth - reserved - GAP * (TOP_ROW.length + 1),
    ry,
  );
  const bottomRx = rowRadius(
    BOTTOM_ROW,
    canvasWidth - GAP * (BOTTOM_ROW.length + 1),
    ry,
  );

  const rings = {
    ...placeRow(TOP_ROW, topRx, stage.legendLeft + GAP, top + hullHeight / 2),
    ...placeRow(BOTTOM_ROW, bottomRx, GAP, top + hullHeight * 1.5 + ROW_GAP),
  };

  const positions: Record<string, Point> = {};
  for (const cluster of clusters) {
    const ring = rings[cluster.id];
    const members = memberIds(cluster.id);
    ringAngles(members.length).forEach((angle, index) => {
      positions[members[index]] = {
        x: ring.center.x + Math.cos(angle) * ring.rx,
        y: ring.center.y + Math.sin(angle) * ry,
      };
    });
  }

  const hulls = clusters.map(cluster => {
    const xs = memberIds(cluster.id).map(id => positions[id].x);
    return {
      id: cluster.id,
      label: cluster.label,
      bounds: {
        x: Math.min(...xs) - PAD.x,
        y: rings[cluster.id].center.y - hullHeight / 2,
        width: Math.max(...xs) - Math.min(...xs) + PAD.x * 2,
        height: hullHeight,
      },
    };
  });

  return {
    width: canvasWidth,
    height,
    positions,
    hulls,
    edges: edgeGeometry(positions),
  };
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
    return (index - (total - 1) / 2) * 44;
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

/** Path geometry for every edge, in the same order as `edges`. */
function edgeGeometry(positions: Record<string, Point>): EdgeGeometry[] {
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
    const end = boundaryPoint(to, offset === 0 ? from : control, 9);

    return {
      edge,
      path:
        offset === 0
          ? `M ${start.x} ${start.y} L ${end.x} ${end.y}`
          : `M ${start.x} ${start.y} Q ${control.x} ${control.y} ` +
            `${end.x} ${end.y}`,
    };
  });
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

/** Every edge touching `id`. */
export function edgesOf(id: string): Edge[] {
  return edges.filter(edge => edge.from === id || edge.to === id);
}
