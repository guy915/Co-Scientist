import {Easing, interpolate} from 'remotion';

/** The rate every film is authored in: scene frame numbers are 30 fps frames, even in the 60 fps master. */
export const FPS = 30;
/** One beat at 120 bpm. Every cut and accent lands on this grid so the score can hit it. */
export const BEAT = 15;

// Material 3 motion curves; Google's launch films move on these.
export const emphasized = Easing.bezier(0.2, 0, 0, 1);
export const decel = Easing.bezier(0.05, 0.7, 0.1, 1);
export const accel = Easing.bezier(0.3, 0, 0.8, 0.15);

/** 0→1 over [start, start + dur], clamped. */
export const ramp = (f: number, start: number, dur: number, ease = decel) =>
  interpolate(f, [start, start + dur], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: ease,
  });

/** In over `dur` at `start`, out over `outDur` at `end`: a visibility envelope. */
export const envelope = (f: number, start: number, end: number, dur = 12, outDur = 10) =>
  ramp(f, start, dur) * (1 - ramp(f, end - outDur, outDur, accel));

export const mix = (a: number, b: number, t: number) => a + (b - a) * t;

export interface Pose {
  f: number;
  x?: number;
  y?: number;
  scale?: number;
  rx?: number;
  ry?: number;
  rz?: number;
  opacity?: number;
  glow?: number;
}

const POSE_DEFAULTS = {x: 0, y: 0, scale: 1, rx: 0, ry: 0, rz: 0, opacity: 1, glow: 0.7};
type Resolved = typeof POSE_DEFAULTS;

/**
 * Camera keyframes: each key inherits unset fields from the one before, and
 * every segment eases on the emphasized curve. Holds before the first key and
 * after the last.
 */
export const posed = (f: number, keys: Pose[]): Resolved => {
  const full: (Resolved & {f: number})[] = [];
  keys.forEach((k, i) => full.push({...(i ? full[i - 1] : POSE_DEFAULTS), ...k}));
  if (f <= full[0].f) return full[0];
  for (let i = 1; i < full.length; i++) {
    const a = full[i - 1];
    const b = full[i];
    if (f <= b.f) {
      const t = ramp(f, a.f, b.f - a.f, emphasized);
      const out = {} as Resolved;
      (Object.keys(POSE_DEFAULTS) as (keyof Resolved)[]).forEach(k => (out[k] = mix(a[k], b[k], t)));
      return out;
    }
  }
  return full[full.length - 1];
};
