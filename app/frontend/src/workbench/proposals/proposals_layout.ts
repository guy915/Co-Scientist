// Geometry for the proposals graph, computed from the space it is given.
//
// Every length below is a base size in CSS pixels. The layout multiplies all
// of them by one factor, chosen so the drawing exactly fits the stage: the
// page never scrolls, and nothing is ever transform-scaled, so text is drawn
// at a real font size rather than stretched.
//
// The legends are part of that single factor — their width is derived from
// it rather than measured, and their type scales with it — so the graph and
// the legends keep the same proportions at every window size and zoom level.
// That is what a fitted viewBox got wrong: it resized the drawing while
// leaving the fixed-size legends alone.
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

/** Base node box. Labels wrap to at most two lines inside it. */
const NODE_BASE = {width: 186, height: 54};

/** One spacing value, used between clusters and around the rows. */
const GAP_BASE = 40;

/** Space between the two rows. */
const ROW_GAP_BASE = 48;

/** Breathing room between a cluster's outermost nodes and its hull. */
const PAD_BASE = {x: NODE_BASE.width / 2 + 26, y: NODE_BASE.height / 2 + 32};

/** Smallest empty space allowed between two node boxes. */
const CLEAR_BASE = 26;

/** Ring half-height at full size. */
const RY_BASE = 96;

/**
 * Legend card width at full size. Derived, not measured: the card is sized
 * in `em` against the scaled root size, so its width is always this times
 * the scale. Measuring it instead would make the scale depend on a length
 * that depends on the scale.
 */
const LEGEND_BASE = 216;

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
  /** Everything below is already multiplied by this; it also sizes type. */
  scale: number;
  node: {width: number; height: number};
  positions: Record<string, Point>;
  hulls: {id: ClusterId; label: string; bounds: Box}[];
  edges: EdgeGeometry[];
}

/** The space the graph has to work with, in CSS pixels. */
export interface Stage {
  width: number;
  height: number;
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
 * fail vertically constrain the horizontal radius. Computed at base size and
 * scaled with everything else.
 */
function minimumRx(count: number): number {
  const angles = ringAngles(count);
  let required = 0;
  for (let i = 0; i < count; i++) {
    for (let j = i + 1; j < count; j++) {
      const dSin = Math.abs(Math.sin(angles[i]) - Math.sin(angles[j]));
      if (dSin * RY_BASE - NODE_BASE.height >= CLEAR_BASE) continue;
      const dCos = Math.abs(Math.cos(angles[i]) - Math.cos(angles[j]));
      if (dCos < 1e-6) continue;
      required = Math.max(required, (NODE_BASE.width + CLEAR_BASE) / dCos);
    }
  }
  return required;
}

function memberIds(clusterId: ClusterId): string[] {
  return nodes.filter(node => node.cluster === clusterId).map(node => node.id);
}

/** Hull width at base size for a cluster whose ring has radius `rx`. */
function hullWidth(clusterId: ClusterId, rx: number): number {
  return extentFactor(memberIds(clusterId).length) * rx + PAD_BASE.x * 2;
}

/** The ring radius below which a row's nodes would start overlapping. */
function minimumRowRadius(row: ClusterId[]): number {
  return Math.max(...row.map(id => minimumRx(memberIds(id).length)));
}

/** Width a row needs at its tightest, including the gaps around it. */
function minimumRowWidth(row: ClusterId[], reserved: number): number {
  const rx = minimumRowRadius(row);
  const hulls = row.reduce((total, id) => total + hullWidth(id, rx), 0);
  return hulls + GAP_BASE * (row.length + 1) + reserved;
}

/**
 * The ring radius that makes a row fill `available`, never smaller than the
 * radius each cluster needs to keep its own nodes apart.
 */
function rowRadius(row: ClusterId[], available: number): number {
  const factors = row.reduce(
    (total, id) => total + extentFactor(memberIds(id).length),
    0,
  );
  const forNodes = available - PAD_BASE.x * 2 * row.length;
  const fitted = factors > 0 ? forNodes / factors : 0;
  return Math.max(fitted, minimumRowRadius(row));
}

/** The narrowest and shortest the whole drawing can be drawn, at base size. */
const MINIMUM = {
  width: Math.max(
    minimumRowWidth(TOP_ROW, LEGEND_BASE * 2),
    minimumRowWidth(BOTTOM_ROW, 0),
  ),
  height: (RY_BASE + PAD_BASE.y) * 4 + ROW_GAP_BASE,
};

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
    x += width + GAP_BASE;
  }
  return placed;
}

/**
 * Lay the whole graph out inside `stage`.
 *
 * One scale is chosen so the drawing fits the stage in both axes; every
 * length is then multiplied by it. The top row is placed between the legend
 * cards with an equal gap on each side and between its clusters, and the
 * bottom row runs the full width.
 */
export function computeLayout(stage: Stage): Layout {
  const width = stage.width || FALLBACK.width;
  const height = stage.height || FALLBACK.height;

  // Never larger than base size, and never so large that it overflows: this
  // is what keeps the page free of scrollbars in both directions.
  const scale = Math.min(1, width / MINIMUM.width, height / MINIMUM.height);

  // Work in base units, then scale once at the end.
  const room = {width: width / scale, height: height / scale};
  const legend = LEGEND_BASE;

  const hullHeight = (RY_BASE + PAD_BASE.y) * 2;
  const top = Math.max(0, (room.height - (hullHeight * 2 + ROW_GAP_BASE)) / 2);

  // The top row shares its line with the legends: one gap to the left card,
  // one between the clusters, one to the right card.
  const topRx = rowRadius(
    TOP_ROW,
    room.width - legend * 2 - GAP_BASE * (TOP_ROW.length + 1),
  );
  const bottomRx = rowRadius(
    BOTTOM_ROW,
    room.width - GAP_BASE * (BOTTOM_ROW.length + 1),
  );

  const rings = {
    ...placeRow(TOP_ROW, topRx, legend + GAP_BASE, top + hullHeight / 2),
    ...placeRow(
      BOTTOM_ROW,
      bottomRx,
      GAP_BASE,
      top + hullHeight * 1.5 + ROW_GAP_BASE,
    ),
  };

  const positions: Record<string, Point> = {};
  for (const cluster of clusters) {
    const ring = rings[cluster.id];
    const members = memberIds(cluster.id);
    ringAngles(members.length).forEach((angle, index) => {
      positions[members[index]] = {
        x: (ring.center.x + Math.cos(angle) * ring.rx) * scale,
        y: (ring.center.y + Math.sin(angle) * RY_BASE) * scale,
      };
    });
  }

  const hulls = clusters.map(cluster => {
    const xs = memberIds(cluster.id).map(id => positions[id].x);
    return {
      id: cluster.id,
      label: cluster.label,
      bounds: {
        x: Math.min(...xs) - PAD_BASE.x * scale,
        y: (rings[cluster.id].center.y - hullHeight / 2) * scale,
        width: Math.max(...xs) - Math.min(...xs) + PAD_BASE.x * 2 * scale,
        height: hullHeight * scale,
      },
    };
  });

  return {
    width,
    height,
    scale,
    node: {
      width: NODE_BASE.width * scale,
      height: NODE_BASE.height * scale,
    },
    positions,
    hulls,
    edges: edgeGeometry(positions, scale),
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
function boundaryPoint(
  box: Point,
  toward: Point,
  pad: number,
  scale: number,
): Point {
  const dx = toward.x - box.x;
  const dy = toward.y - box.y;
  if (dx === 0 && dy === 0) return box;
  const halfWidth = (NODE_BASE.width / 2 + pad) * scale;
  const halfHeight = (NODE_BASE.height / 2 + pad) * scale;
  // Stretch the direction vector until it first touches a side, then take
  // whichever side it reaches first.
  const reach = Math.min(
    dx === 0 ? Infinity : halfWidth / Math.abs(dx),
    dy === 0 ? Infinity : halfHeight / Math.abs(dy),
  );
  return {x: box.x + dx * reach, y: box.y + dy * reach};
}

/** Path geometry for every edge, in the same order as `edges`. */
function edgeGeometry(
  positions: Record<string, Point>,
  scale: number,
): EdgeGeometry[] {
  return edges.map((edge, index) => {
    const from = positions[edge.from];
    const to = positions[edge.to];
    const offset = edgeOffsets[index] * scale;

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
    const start = boundaryPoint(from, offset === 0 ? to : control, 4, scale);
    const end = boundaryPoint(to, offset === 0 ? from : control, 9, scale);

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
