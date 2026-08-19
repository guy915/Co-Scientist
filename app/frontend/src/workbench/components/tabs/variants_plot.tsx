import {type CodeVariant, type DiscoveryObjective} from '@/api/runs';
import {formatMeasured} from '@/lib/objectives';

// Plot geometry, in the SVG's own user units. The viewBox scales to the
// container, so these are proportions rather than pixels.
const WIDTH = 720;
const HEIGHT = 260;
const PAD_LEFT = 52;
const PAD_RIGHT = 16;
const PAD_TOP = 16;
const PAD_BOTTOM = 32;

/** One point on the breakthrough plot. */
interface Point {
  ordinal: number;
  // The best fitness reached at or before this attempt. Never null: the
  // line only starts once something has scored.
  best: number;
  // Whether this attempt is the one that set the record.
  isRecord: boolean;
}

/**
 * Builds the running-best series from a run's attempts.
 *
 * Unscored attempts advance the x axis without moving the line, which is
 * the whole point of plotting against the attempt number rather than
 * against the scored attempts alone: a run that took forty tries to
 * improve should look like it took forty tries.
 *
 * @param variants Every attempt, in ordinal order.
 * @returns The series, empty until something has scored.
 */
export function runningBest(variants: CodeVariant[]): Point[] {
  const points: Point[] = [];
  let best: number | null = null;
  for (const variant of variants) {
    const isRecord = beatsRecord(variant.fitness, best);
    if (isRecord) best = variant.fitness;
    if (best !== null) points.push({ordinal: variant.ordinal, best, isRecord});
  }
  return points;
}

// Whether a variant's score is a new record. An unscored variant never is
// -- null means "no position in the ordering", so it can neither set a
// record nor be compared against one.
function beatsRecord(fitness: number | null, best: number | null): boolean {
  if (fitness === null) return false;
  return best === null || fitness > best;
}

// Maps a value in [lo, hi] onto [from, to]. A degenerate range (every
// attempt scoring identically) would divide by zero, so it centres
// instead -- a flat line through the middle, which is what happened.
function scale(
  value: number,
  lo: number,
  hi: number,
  from: number,
  to: number,
): number {
  if (hi === lo) return (from + to) / 2;
  return from + ((value - lo) / (hi - lo)) * (to - from);
}

// The axis labels read in the metric's own units, so a minimized
// objective is un-negated here rather than printing a negative number of
// seconds beside a report that prints a positive one.
function formatScore(value: number, objective?: DiscoveryObjective): string {
  return formatMeasured(value, objective);
}

/**
 * The breakthrough plot: best score so far against attempt number.
 *
 * Renders nothing when no attempt has scored yet -- an axis with no line
 * reads as "the plot is broken", where an explicit empty state reads as
 * "nothing has worked yet", which is the true and more useful statement.
 */
export function VariantsPlot({
  variants,
  objective,
}: {
  variants: CodeVariant[];
  objective?: DiscoveryObjective;
}) {
  const points = runningBest(variants);
  const attempts = variants.length;
  if (points.length === 0 || attempts === 0) {
    return (
      <p className="m-0 py-8 text-center text-sm text-cosci-muted">
        No attempt has produced a score yet.
      </p>
    );
  }

  const lo = points[0].best;
  const hi = points[points.length - 1].best;
  const x = (ordinal: number) =>
    scale(ordinal, 1, Math.max(attempts, 2), PAD_LEFT, WIDTH - PAD_RIGHT);
  const y = (value: number) =>
    scale(value, lo, hi, HEIGHT - PAD_BOTTOM, PAD_TOP);

  // A step line, not a straight one: the best score holds flat until an
  // attempt beats it, and interpolating between records would draw steady
  // progress that never happened.
  const path = points
    .map((point, index) => {
      const move =
        index === 0 ? `M ${x(point.ordinal)}` : `L ${x(point.ordinal)}`;
      const prior =
        index === 0
          ? ''
          : `L ${x(point.ordinal)} ${y(points[index - 1].best)} `;
      return `${prior}${move} ${y(point.best)}`;
    })
    .join(' ');

  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      className="h-auto w-full"
      role="img"
      aria-label={
        `Best score against attempt number: ${formatScore(hi, objective)} ` +
        `after ${attempts} attempts`
      }
    >
      <line
        x1={PAD_LEFT}
        y1={HEIGHT - PAD_BOTTOM}
        x2={WIDTH - PAD_RIGHT}
        y2={HEIGHT - PAD_BOTTOM}
        className="stroke-cosci-border"
        strokeWidth={1}
      />
      <text
        x={PAD_LEFT - 8}
        y={PAD_TOP + 4}
        textAnchor="end"
        className="fill-cosci-muted text-[11px]"
      >
        {formatScore(hi, objective)}
      </text>
      <text
        x={PAD_LEFT - 8}
        y={HEIGHT - PAD_BOTTOM}
        textAnchor="end"
        className="fill-cosci-muted text-[11px]"
      >
        {formatScore(lo, objective)}
      </text>
      <text
        x={WIDTH - PAD_RIGHT}
        y={HEIGHT - 8}
        textAnchor="end"
        className="fill-cosci-muted text-[11px]"
      >
        {attempts} attempts
      </text>
      <path
        d={path}
        fill="none"
        className="stroke-cosci-accent"
        strokeWidth={2}
      />
      {points
        .filter(point => point.isRecord)
        .map(point => (
          <circle
            key={point.ordinal}
            cx={x(point.ordinal)}
            cy={y(point.best)}
            r={4}
            className="fill-cosci-accent"
          >
            <title>
              {`Attempt ${point.ordinal}: ${formatScore(point.best)}`}
            </title>
          </circle>
        ))}
    </svg>
  );
}
