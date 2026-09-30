// The Tournament section's rating chart: eight simulated ideas over 64
// matches, computed with the real Elo update when the page loads. The lines
// draw themselves in when the chart scrolls into view.

import {useMemo, useRef} from 'react';
import {joinClasses} from '../classes';
import {simulateEloHistory} from './home_landing_elo';
import {type MotionProps, useInView} from './home_landing_hooks';

const LO = 1100;
const HI = 1320;
const LEFT = 44;
const PLOT_W = 500;
const BASE_Y = 290;
const PLOT_H = 270;
const GRID = [1100, 1150, 1200, 1250, 1300];

function useChartGeometry() {
  return useMemo(() => {
    const {history, leader} = simulateEloHistory();
    const matches = history.length - 1;
    const x = (m: number) => LEFT + (m / matches) * PLOT_W;
    const y = (elo: number) => BASE_Y - ((elo - LO) / (HI - LO)) * PLOT_H;
    const lines = history[0].map((_, i) =>
      history.map((h, m) => `${x(m).toFixed(1)} ${y(h[i]).toFixed(1)}`),
    );
    const final = history[matches][leader];
    return {
      matches,
      leader,
      final,
      paths: lines.map(points => 'M' + points.join('L')),
      grid: GRID.map(elo => ({elo, y: y(elo)})),
      end: {x: x(matches), y: y(final)},
    };
  }, []);
}

/** The Elo chart panel. */
export function LandingEloChart({reduceMotion}: MotionProps) {
  const ref = useRef<HTMLDivElement | null>(null);
  const seen = useInView(ref, {threshold: 0.35});
  const chart = useChartGeometry();
  // The leader's line goes last so it draws on top.
  const order = chart.paths
    .map((d, i) => ({d, i}))
    .sort(
      (a, b) => Number(a.i === chart.leader) - Number(b.i === chart.leader),
    );
  return (
    <div
      ref={ref}
      className={joinClasses(
        'ucs-landing-panel ucs-landing-elo',
        (seen || reduceMotion) && 'is-drawn',
      )}
    >
      <h3 className="ucs-landing-panel-title">Ratings over one tournament</h3>
      <svg
        viewBox="0 0 560 320"
        role="img"
        aria-label="Line chart of Elo ratings over 64 matches for 8 simulated ideas; one idea climbs clearly above the rest."
      >
        <g className="ucs-landing-elo-grid">
          {chart.grid.map(g => (
            <g key={g.elo}>
              <line x1={LEFT} x2={LEFT + PLOT_W} y1={g.y} y2={g.y} />
              <text x="0" y={g.y + 4}>
                {g.elo}
              </text>
            </g>
          ))}
          <text x={LEFT} y="314">
            0
          </text>
          <text x={LEFT + PLOT_W - 14} y="314">
            {chart.matches}
          </text>
        </g>
        {order.map(({d, i}) => (
          <path
            key={i}
            d={d}
            pathLength={1}
            className={joinClasses(
              'ucs-landing-elo-line',
              i === chart.leader && 'is-leader',
            )}
          />
        ))}
        <circle
          className="ucs-landing-elo-end"
          cx={chart.end.x}
          cy={chart.end.y}
          r="5"
        />
      </svg>
      <div className="ucs-landing-elo-legend">
        <span>Matches</span>
        <span>
          <b>{Math.round(chart.final)}</b> final Elo of the leader
        </span>
      </div>
    </div>
  );
}
