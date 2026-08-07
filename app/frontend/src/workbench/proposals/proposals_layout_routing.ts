// Edge routing for the proposals graph: turns node positions into SVG path
// data, bending each edge only as much as the obstructions demand. Base
// sizes and shared types live in proposals_layout_metrics.ts; the ring
// placement that produces the positions lives in proposals_layout.ts.

import {edges, nodes, type Edge} from './proposals_data';
import {
  NODE_BASE,
  type EdgeGeometry,
  type Point,
} from './proposals_layout_metrics';

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

/**
 * Offsets tried when routing an edge, in order. Zero is a straight line; the
 * rest bow the curve to one side or the other by growing amounts, so a
 * blocked edge is nudged as little as the obstruction allows. Both signs are
 * offered at each distance: a curve is free to bow either way.
 */
const OFFSETS = [
  0, 20, -20, 40, -40, 60, -60, 80, -80, 100, -100, 120, -120, 140, -140, 160,
  -160, 180, -180, 200, -200, 220, -220, 240, -240, 260, -260, 280, -280, 300,
  -300, 320, -320,
];

/** How close two edges may run before they read as one line. */
const EDGE_CLEARANCE = 9;

/** How close an edge may pass to a node it does not connect. */
const NODE_CLEARANCE = 10;

/** Points sampled along an edge when testing it against its neighbours. */
const SAMPLES = 16;

interface Route {
  path: string;
  points: Point[];
}

/** Points along the straight (offset 0) or quadratic route, for tests. */
function sampleRoute(
  start: Point,
  control: Point,
  end: Point,
  offset: number,
): Point[] {
  const points: Point[] = [];
  for (let i = 0; i <= SAMPLES; i++) {
    const t = i / SAMPLES;
    if (offset === 0) {
      points.push({
        x: start.x + (end.x - start.x) * t,
        y: start.y + (end.y - start.y) * t,
      });
      continue;
    }
    const inverse = 1 - t;
    points.push({
      x:
        inverse * inverse * start.x +
        2 * inverse * t * control.x +
        t * t * end.x,
      y:
        inverse * inverse * start.y +
        2 * inverse * t * control.y +
        t * t * end.y,
    });
  }
  return points;
}

/** Builds one candidate route for an edge at the given perpendicular offset. */
function route(from: Point, to: Point, offset: number, scale: number): Route {
  // Control point sits perpendicular to the midpoint, bowing the curve away
  // from whatever the straight line would have run into.
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const length = Math.hypot(dx, dy) || 1;
  const control: Point = {
    x: (from.x + to.x) / 2 + (-dy / length) * offset,
    y: (from.y + to.y) / 2 + (dx / length) * offset,
  };

  // Trim both ends to the node boundary, aiming at the control point so
  // curved edges leave and arrive at sensible angles.
  const start = boundaryPoint(from, offset === 0 ? to : control, 4, scale);
  const end = boundaryPoint(to, offset === 0 ? from : control, 9, scale);

  const points = sampleRoute(start, control, end, offset);

  return {
    path:
      offset === 0
        ? `M ${start.x} ${start.y} L ${end.x} ${end.y}`
        : `M ${start.x} ${start.y} Q ${control.x} ${control.y} ` +
          `${end.x} ${end.y}`,
    points,
  };
}

/** How many unrelated nodes a route passes through. */
function nodeHits(
  candidate: Route,
  edge: Edge,
  positions: Record<string, Point>,
  scale: number,
): number {
  const halfWidth = (NODE_BASE.width / 2) * scale + NODE_CLEARANCE;
  const halfHeight = (NODE_BASE.height / 2) * scale + NODE_CLEARANCE;
  let hits = 0;
  for (const node of nodes) {
    if (node.id === edge.from || node.id === edge.to) continue;
    const at = positions[node.id];
    const through = candidate.points.some(
      point =>
        Math.abs(point.x - at.x) < halfWidth &&
        Math.abs(point.y - at.y) < halfHeight,
    );
    if (through) hits++;
  }
  return hits;
}

/**
 * Whether two routes run together rather than merely crossing. Crossings are
 * unavoidable in a graph this dense and read fine; two lines travelling side
 * by side at the same angle are what looks like a single edge.
 */
function runsAlongside(a: Route, b: Route): boolean {
  let close = 0;
  for (const point of a.points) {
    for (const other of b.points) {
      if (Math.hypot(point.x - other.x, point.y - other.y) < EDGE_CLEARANCE) {
        close++;
        if (close > 2) return true;
        break;
      }
    }
  }
  return false;
}

/**
 * Path geometry for every edge, in the same order as `edges`.
 *
 * Every offset is scored — nodes passed through, edges run alongside, and a
 * small penalty for bending at all — and the best is taken. Scoring rather
 * than taking the first clear route matters for the long edges that cross a
 * cluster: no single bend clears them, so the cheapest one should win rather
 * than falling back to a straight line through three nodes. The order is
 * fixed, so the result is deterministic.
 */
function bestRoute(
  edge: Edge,
  positions: Record<string, Point>,
  scale: number,
  placed: PlacedRoute[],
): Route {
  const from = positions[edge.from];
  const to = positions[edge.to];
  // The straight line is always a valid answer, so it seeds the search
  // and there is never an empty result to guard against.
  let best = route(from, to, 0, scale);
  let bestCost = Infinity;
  for (const offset of OFFSETS) {
    const candidate = route(from, to, offset * scale, scale);
    const overlaps = placed.filter(other =>
      runsAlongside(candidate, other.route),
    );
    const twin = overlaps.some(other => sameEndpoints(other.edge, edge));
    const cost =
      nodeHits(candidate, edge, positions, scale) * 100 +
      overlaps.length * 60 +
      (twin ? TWIN_OVERLAP_COST : 0) +
      Math.abs(offset) / 100;
    if (cost < bestCost) {
      best = candidate;
      bestCost = cost;
    }
    if (cost < 1) break;
  }
  return best;
}

/** Whether two edges join the same pair of nodes, in either direction. */
function sameEndpoints(a: Edge, b: Edge): boolean {
  return (
    (a.from === b.from && a.to === b.to) || (a.from === b.to && a.to === b.from)
  );
}

// An edge running alongside an unrelated one is a legibility cost the router
// trades against passing through a node. Running alongside its own twin --
// the second edge of a doubled pair, which by construction shares both
// endpoints and therefore its whole length -- is not a degree of that: it
// hides one of the two relationships completely. Priced above a node hit so
// the twin always takes the detour.
const TWIN_OVERLAP_COST = 400;

/** A routed edge and the edge it belongs to, for twin/overlap scoring. */
interface PlacedRoute {
  edge: Edge;
  route: Route;
}

export function edgeGeometry(
  positions: Record<string, Point>,
  scale: number,
): EdgeGeometry[] {
  const placed: PlacedRoute[] = [];
  const routed: string[] = [];
  // Hardest first: the longest edges are the ones that have to cross a
  // cluster, and they need the widest choice of bends. Placing in array
  // order would hand that choice to the short edges and leave the long
  // ones picking between a node hit and running alongside a neighbour.
  // Ties break on index, so the order is still fully determined.
  const order = edges
    .map((edge, index) => ({
      index,
      span: Math.hypot(
        positions[edge.to].x - positions[edge.from].x,
        positions[edge.to].y - positions[edge.from].y,
      ),
    }))
    .sort((a, b) => b.span - a.span || a.index - b.index);
  for (const {index} of order) {
    const best = bestRoute(edges[index], positions, scale, placed);
    placed.push({edge: edges[index], route: best});
    routed[index] = best.path;
  }
  // Drawing order stays authoring order, so the SVG is unchanged in
  // structure and only the paths differ.
  return edges.map((edge, index) => ({edge, path: routed[index]}));
}
