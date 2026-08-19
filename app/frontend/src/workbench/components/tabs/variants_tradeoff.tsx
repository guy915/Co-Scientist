import {type CodeVariant, type DiscoveryObjective} from '@/api/runs';

const WIDTH = 720;
const HEIGHT = 300;
const PAD = 48;

// Maps a value in [lo, hi] onto [from, to], centring a degenerate range
// rather than dividing by zero.
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

// Sign-corrected scores are higher-is-better on every axis, so a
// minimized metric arrives negated. Undo that for the label, or the
// reader sees "-2.4 seconds".
function axisLabel(objective: DiscoveryObjective): string {
  const arrow = objective.direction === 'minimize' ? '↓' : '↑';
  return `${objective.metric} ${arrow}`;
}

function displayValue(value: number, objective: DiscoveryObjective): number {
  const raw = objective.direction === 'minimize' ? -value : value;
  return Math.round(raw * 1000) / 1000;
}

interface Placed {
  variant: CodeVariant;
  x: number;
  y: number;
}

function placedPoints(variants: CodeVariant[]): Placed[] {
  const usable = variants.filter(
    v =>
      v.objective_values.length >= 2 &&
      v.objective_values[0] !== null &&
      v.objective_values[1] !== null,
  );
  if (usable.length === 0) return [];
  const xs = usable.map(v => v.objective_values[0] as number);
  const ys = usable.map(v => v.objective_values[1] as number);
  const [xLo, xHi] = [Math.min(...xs), Math.max(...xs)];
  const [yLo, yHi] = [Math.min(...ys), Math.max(...ys)];
  return usable.map((variant, index) => ({
    variant,
    x: scale(xs[index], xLo, xHi, PAD, WIDTH - PAD),
    y: scale(ys[index], yLo, yHi, HEIGHT - PAD, PAD),
  }));
}

/**
 * The trade-off view: objective one against objective two.
 *
 * A run optimizing two things has no single best program, so plotting
 * only the primary score would show a ranking that does not exist. This
 * shows the shape of the trade instead, with the Pareto front — the
 * variants nothing beats on both axes at once — marked. Those are the
 * real choices; everything else is beaten by one of them outright.
 */
export function VariantsTradeoff({
  variants,
  objectives,
}: {
  variants: CodeVariant[];
  objectives: DiscoveryObjective[];
}) {
  if (objectives.length < 2) return null;
  const points = placedPoints(variants);
  if (points.length === 0) {
    return (
      <p className="m-0 py-8 text-center text-sm text-cosci-muted">
        No attempt has scored on both objectives yet.
      </p>
    );
  }
  const front = points.filter(p => p.variant.is_pareto_optimal);
  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      className="h-auto w-full"
      role="img"
      aria-label={
        `${objectives[0].metric} against ${objectives[1].metric}, ` +
        `${front.length} of ${points.length} scored attempts on the ` +
        'Pareto front'
      }
    >
      <line
        x1={PAD}
        y1={HEIGHT - PAD}
        x2={WIDTH - PAD}
        y2={HEIGHT - PAD}
        className="stroke-cosci-border"
      />
      <line
        x1={PAD}
        y1={PAD}
        x2={PAD}
        y2={HEIGHT - PAD}
        className="stroke-cosci-border"
      />
      <text
        x={WIDTH - PAD}
        y={HEIGHT - PAD + 20}
        textAnchor="end"
        className="fill-cosci-muted text-[11px]"
      >
        {axisLabel(objectives[0])}
      </text>
      <text x={PAD} y={PAD - 14} className="fill-cosci-muted text-[11px]">
        {axisLabel(objectives[1])}
      </text>
      {points.map(point => (
        <circle
          key={point.variant.id}
          cx={point.x}
          cy={point.y}
          r={point.variant.is_pareto_optimal ? 5 : 3.5}
          className={
            point.variant.is_pareto_optimal
              ? 'fill-cosci-accent'
              : 'fill-cosci-muted opacity-50'
          }
        >
          <title>
            {`Attempt ${point.variant.ordinal}: ` +
              `${objectives[0].metric} ` +
              `${displayValue(
                point.variant.objective_values[0] as number,
                objectives[0],
              )}, ${objectives[1].metric} ` +
              `${displayValue(
                point.variant.objective_values[1] as number,
                objectives[1],
              )}`}
          </title>
        </circle>
      ))}
    </svg>
  );
}
