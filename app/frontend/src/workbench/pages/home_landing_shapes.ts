// Material 3 Expressive shapes for the landing page, drawn as SVG paths on a
// 100x100 box. Every shape is sampled at the same number of points, so any
// two can be morphed into each other by interpolating point by point.

import {type RefObject, useCallback, useRef} from 'react';

type Point = readonly [number, number];

const SAMPLES = 180;
const TAU = Math.PI * 2;

// Samples a closed shape whose radius varies with the angle (0 = top).
function polar(radius: (angle: number) => number): Point[] {
  return Array.from({length: SAMPLES}, (_, i) => {
    const angle = (i / SAMPLES) * TAU - Math.PI / 2;
    const r = radius(angle);
    return [50 + r * Math.cos(angle), 50 + r * Math.sin(angle)] as const;
  });
}

// Samples a superellipse, which reads as a pill with soft corners.
function pill(halfWidth: number, halfHeight: number): Point[] {
  const p = 8;
  return Array.from({length: SAMPLES}, (_, i) => {
    const angle = (i / SAMPLES) * TAU;
    const c = Math.cos(angle);
    const s = Math.sin(angle);
    const k = Math.pow(
      Math.pow(Math.abs(c) / halfWidth, p) +
        Math.pow(Math.abs(s) / halfHeight, p),
      -1 / p,
    );
    return [50 + k * c, 50 + k * s] as const;
  });
}

const SHAPES = {
  circle: polar(() => 46),
  cookie12: polar(a => 44 + 3.2 * Math.cos(12 * a)),
  cookie7: polar(a => 43 + 4.2 * Math.cos(7 * a)),
  flower: polar(a => 40 + 8 * Math.pow(Math.abs(Math.cos(4 * a)), 0.6)),
  clover: polar(a => 36 + 12 * Math.pow(Math.abs(Math.cos(2 * a)), 0.9)),
  sunny: polar(a => 44 + 3.4 * Math.cos(8 * a + Math.PI)),
  gem: polar(a => 44 - 5 * Math.pow(Math.abs(Math.sin(3 * a)), 1.2)),
  pill: pill(47, 30),
};

/** The names of the shapes this module can draw. */
export type ShapeName = keyof typeof SHAPES;

function toPath(points: readonly Point[]): string {
  return (
    'M' +
    points.map(([x, y]) => `${x.toFixed(2)} ${y.toFixed(2)}`).join('L') +
    'Z'
  );
}

/** Returns the SVG path data for a named shape. */
export function shapePath(name: ShapeName): string {
  return toPath(SHAPES[name]);
}

/** Returns the path `k` of the way (0-1) from one shape to another. */
export function blendShapes(from: ShapeName, to: ShapeName, k: number): string {
  const a = SHAPES[from];
  const b = SHAPES[to];
  return toPath(
    a.map(([x, y], i) => [x + (b[i][0] - x) * k, y + (b[i][1] - y) * k]),
  );
}

const MORPH_MS = 700;

/**
 * Morphs the referenced path between its resting shape and a circle, the M3
 * Expressive hover response. Writes the `d` attribute directly each frame
 * rather than through state, so a morph costs no React renders.
 *
 * @param rest The shape the path shows at rest.
 * @param reduceMotion When true the path snaps instead of animating.
 * @returns The path ref and the enter/leave handlers to attach.
 */
export function useShapeMorph(
  rest: ShapeName,
  reduceMotion: boolean,
): {
  pathRef: RefObject<SVGPathElement | null>;
  toCircle: () => void;
  toRest: () => void;
} {
  const pathRef = useRef<SVGPathElement | null>(null);
  // The token of the morph in flight; a newer morph orphans the older one.
  const token = useRef(0);
  const run = useCallback(
    (from: ShapeName, to: ShapeName) => {
      const path = pathRef.current;
      if (!path) return;
      const id = ++token.current;
      if (reduceMotion) {
        path.setAttribute('d', shapePath(to));
        return;
      }
      const start = performance.now();
      const step = (now: number) => {
        if (token.current !== id) return;
        const t = Math.min(1, (now - start) / MORPH_MS);
        path.setAttribute('d', blendShapes(from, to, 1 - Math.pow(1 - t, 4)));
        if (t < 1) requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
    },
    [reduceMotion],
  );
  return {
    pathRef,
    toCircle: useCallback(() => run(rest, 'circle'), [run, rest]),
    toRest: useCallback(() => run('circle', rest), [run, rest]),
  };
}
