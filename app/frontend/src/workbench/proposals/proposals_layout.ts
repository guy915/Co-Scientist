// Geometry for the proposals graph, computed from the space it is given.
//
// Every length is a base size in CSS pixels (see
// proposals_layout_metrics.ts). The layout multiplies all of them by one
// factor, chosen so the drawing exactly fits the stage: the page never
// scrolls, and nothing is ever transform-scaled, so text is drawn at a real
// font size rather than stretched.
//
// The legends keep their own fixed size — they are ordinary UI, not part of
// the drawing — so the layout reserves their width and fits the graph into
// what is left. The gap from a legend to the nearest cluster is one of the
// drawing's own gaps, so it stays consistent with every other gap.
//
// Content lives in proposals_data.ts; colors live in CSS; edge routing lives
// in proposals_layout_routing.ts.

import {clusters, nodes, type ClusterId} from './proposals_data';
import {
  FALLBACK,
  GAP_BASE,
  LEGEND_WIDTH,
  NODE_BASE,
  PAD_BASE,
  CLEAR_BASE,
  ROW_GAP_BASE,
  RY_BASE,
  type Layout,
  type Point,
  type Stage,
} from './proposals_layout_metrics';
import {edgeGeometry} from './proposals_layout_routing';

// The base sizes and geometry types live in proposals_layout_metrics.ts;
// re-exported here so callers keep importing them from the layout module.
export {
  LABEL_WRAP_CHARS,
  LEGEND_WIDTH,
  type Box,
  type EdgeGeometry,
  type Layout,
  type Point,
  type Stage,
} from './proposals_layout_metrics';

// Which row each cluster sits on, left to right. The top row is the one that
// has to share its line with the legends, so it holds the two clusters that
// need the least width.
const TOP_ROW: ClusterId[] = ['evaluation', 'interaction'];
const BOTTOM_ROW: ClusterId[] = ['capabilities', 'knowledge', 'scaling'];

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

/**
 * The narrowest and shortest the drawing can be, at base size. The top row's
 * figure excludes the legends: their width is fixed, so it is subtracted
 * from the space before the scale is worked out rather than scaled with it.
 */
const MINIMUM = {
  topRow: minimumRowWidth(TOP_ROW, 0),
  bottomRow: minimumRowWidth(BOTTOM_ROW, 0),
  height: (RY_BASE + PAD_BASE.y) * 4 + ROW_GAP_BASE,
};

/** One cluster ring: its center point and horizontal radius. */
interface Ring {
  center: Point;
  rx: number;
}

/** Ring centers for one row, laid left to right from `start`. */
function placeRow(
  row: ClusterId[],
  rx: number,
  start: number,
  y: number,
): Record<string, Ring> {
  const placed: Record<string, Ring> = {};
  let x = start;
  for (const id of row) {
    const width = hullWidth(id, rx);
    placed[id] = {center: {x: x + width / 2, y}, rx};
    x += width + GAP_BASE;
  }
  return placed;
}

const HULL_HEIGHT_BASE = (RY_BASE + PAD_BASE.y) * 2;

// One scale fits the drawing to the stage in both axes: never larger than
// base size, and never so large that it overflows — this is what keeps the
// page free of scrollbars in both directions. The top row competes only for
// what the fixed-width legends leave behind.
function layoutScale(width: number, height: number): number {
  return Math.min(
    1,
    Math.max(0, width - LEGEND_WIDTH * 2) / MINIMUM.topRow,
    width / MINIMUM.bottomRow,
    height / MINIMUM.height,
  );
}

// Places both cluster rows in base units. The top row shares its line with
// the legends: one gap to the left card, one between the clusters, one to
// the right card.
function clusterRings(
  room: {width: number; height: number},
  legend: number,
): Record<string, Ring> {
  const top = Math.max(
    0,
    (room.height - (HULL_HEIGHT_BASE * 2 + ROW_GAP_BASE)) / 2,
  );
  const topRx = rowRadius(
    TOP_ROW,
    room.width - legend * 2 - GAP_BASE * (TOP_ROW.length + 1),
  );
  const bottomRx = rowRadius(
    BOTTOM_ROW,
    room.width - GAP_BASE * (BOTTOM_ROW.length + 1),
  );
  return {
    ...placeRow(TOP_ROW, topRx, legend + GAP_BASE, top + HULL_HEIGHT_BASE / 2),
    ...placeRow(
      BOTTOM_ROW,
      bottomRx,
      GAP_BASE,
      top + HULL_HEIGHT_BASE * 1.5 + ROW_GAP_BASE,
    ),
  };
}

// Spreads every cluster's members around its ring, in scaled pixels.
function nodePositions(
  rings: Record<string, Ring>,
  scale: number,
): Record<string, Point> {
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
  return positions;
}

// Bounds each cluster's hull card around its members, in scaled pixels.
function clusterHulls(
  rings: Record<string, Ring>,
  positions: Record<string, Point>,
  scale: number,
): Layout['hulls'] {
  return clusters.map(cluster => {
    const xs = memberIds(cluster.id).map(id => positions[id].x);
    return {
      id: cluster.id,
      label: cluster.label,
      bounds: {
        x: Math.min(...xs) - PAD_BASE.x * scale,
        y: (rings[cluster.id].center.y - HULL_HEIGHT_BASE / 2) * scale,
        width: Math.max(...xs) - Math.min(...xs) + PAD_BASE.x * 2 * scale,
        height: HULL_HEIGHT_BASE * scale,
      },
    };
  });
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
  const scale = layoutScale(width, height);

  // Work in base units, then scale once at the end. The legends are the one
  // length that does not scale, so they convert the other way.
  const room = {width: width / scale, height: height / scale};
  const legend = LEGEND_WIDTH / scale;

  const rings = clusterRings(room, legend);
  const positions = nodePositions(rings, scale);
  const hulls = clusterHulls(rings, positions, scale);

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
