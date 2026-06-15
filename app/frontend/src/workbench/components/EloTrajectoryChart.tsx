/**
 * Copyright 2026 The Co-Scientist Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import {useMemo} from 'react';
import type {Hypothesis, MatchRow} from '@/api/runs';

const PALETTE = [
  'var(--color-th-phase0)',
  'var(--color-th-phase1)',
  'var(--color-th-phase2)',
  'var(--color-th-phase3)',
  'var(--color-th-phase4)',
];

interface Series {
  hypothesisId: string;
  title: string;
  /** Elo at every match index in chronological order (initial 1200 prepended). */
  trajectory: number[];
  finalElo: number;
}

/**
 * Inline SVG line chart of Elo trajectories for the top-K hypotheses.
 * Computed client-side from the persisted match log. Chronological by match id.
 */
export function EloTrajectoryChart({
  matches,
  hypotheses,
  topK = 5,
  initialElo = 1200,
}: {
  matches: MatchRow[];
  hypotheses: Hypothesis[];
  topK?: number;
  initialElo?: number;
}) {
  const series = useMemo<Series[]>(() => {
    if (!matches.length) return [];
    const ordered = [...matches].sort((a, b) => a.id - b.id);

    // Build per-hypothesis Elo trajectory by scanning match history.
    const trajectories = new Map<string, number[]>();
    const setTrack = (id: string, val: number) => {
      const arr = trajectories.get(id) ?? [initialElo];
      arr.push(val);
      trajectories.set(id, arr);
    };
    // Pre-seed with initial Elo so every series starts at 1200 even if its first match is mid-run.
    const seenIds = new Set<string>();
    for (const m of ordered) {
      seenIds.add(m.winner_id);
      seenIds.add(m.loser_id);
    }
    for (const id of seenIds) trajectories.set(id, [initialElo]);

    for (const m of ordered) {
      setTrack(m.winner_id, m.winner_elo_after);
      setTrack(m.loser_id, m.loser_elo_after);
    }

    const titleFor = (id: string) =>
      hypotheses.find(h => h.id === id)?.title ?? id.slice(0, 8);

    return [...trajectories.entries()]
      .map(([id, trajectory]) => ({
        hypothesisId: id,
        title: titleFor(id),
        trajectory,
        finalElo: trajectory[trajectory.length - 1] ?? initialElo,
      }))
      .sort((a, b) => b.finalElo - a.finalElo)
      .slice(0, topK);
  }, [matches, hypotheses, topK, initialElo]);

  if (series.length === 0) {
    return null;
  }

  // Domain: max trajectory length across all series.
  const maxLen = Math.max(...series.map(s => s.trajectory.length));
  const allElos = series.flatMap(s => s.trajectory);
  const minElo = Math.min(initialElo - 20, ...allElos);
  const maxElo = Math.max(initialElo + 20, ...allElos);

  const width = 640;
  const height = 220;
  const padding = {top: 12, right: 12, bottom: 24, left: 40};
  const innerW = width - padding.left - padding.right;
  const innerH = height - padding.top - padding.bottom;

  const x = (i: number) =>
    padding.left + (maxLen <= 1 ? 0 : (i / (maxLen - 1)) * innerW);
  const y = (e: number) =>
    padding.top +
    innerH -
    ((e - minElo) / Math.max(1, maxElo - minElo)) * innerH;

  // Y-axis ticks (5).
  const ticks = 5;
  const yTicks = [...Array(ticks)].map((_, i) =>
    Math.round(minElo + (i / (ticks - 1)) * (maxElo - minElo)),
  );

  return (
    <section
      className="rounded border p-4 wb-fade-in"
      style={{
        borderColor: 'var(--color-th-border)',
        backgroundColor: 'var(--color-th-card)',
      }}
    >
      <header className="flex items-baseline justify-between mb-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide">
          Elo trajectories
        </h2>
        <span className="text-xs" style={{color: 'var(--color-th-muted-fg)'}}>
          top {series.length} · {maxLen - 1} matches
        </span>
      </header>
      <div className="overflow-x-auto">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="w-full h-[220px]"
          role="img"
          aria-label="Elo trajectory chart"
        >
          {/* Y axis grid + labels */}
          {yTicks.map(tick => (
            <g key={tick}>
              <line
                x1={padding.left}
                x2={width - padding.right}
                y1={y(tick)}
                y2={y(tick)}
                stroke="var(--color-th-border)"
                strokeWidth={0.5}
                strokeDasharray="2 3"
              />
              <text
                x={padding.left - 6}
                y={y(tick) + 3}
                textAnchor="end"
                fontSize={10}
                fill="var(--color-th-muted-fg)"
              >
                {tick}
              </text>
            </g>
          ))}
          {/* Initial Elo reference line */}
          <line
            x1={padding.left}
            x2={width - padding.right}
            y1={y(initialElo)}
            y2={y(initialElo)}
            stroke="var(--color-th-muted-fg)"
            strokeWidth={0.5}
            opacity={0.4}
          />
          {/* Series */}
          {series.map((s, idx) => {
            const color = PALETTE[idx % PALETTE.length];
            const path = s.trajectory
              .map(
                (e, i) =>
                  `${i === 0 ? 'M' : 'L'} ${x(i).toFixed(1)} ${y(e).toFixed(1)}`,
              )
              .join(' ');
            return (
              <g key={s.hypothesisId}>
                <path d={path} fill="none" stroke={color} strokeWidth={1.75} />
                {/* Endpoint dot */}
                <circle
                  cx={x(s.trajectory.length - 1)}
                  cy={y(s.finalElo)}
                  r={3}
                  fill={color}
                />
              </g>
            );
          })}
          {/* X axis label */}
          <text
            x={width / 2}
            y={height - 6}
            textAnchor="middle"
            fontSize={10}
            fill="var(--color-th-muted-fg)"
          >
            match index →
          </text>
        </svg>
      </div>
      <ul className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1 mt-2 text-xs">
        {series.map((s, idx) => (
          <li key={s.hypothesisId} className="flex items-center gap-2">
            <span
              className="inline-block w-3 h-1.5 rounded-sm shrink-0"
              style={{backgroundColor: PALETTE[idx % PALETTE.length]}}
              aria-hidden="true"
            />
            <span className="truncate flex-1" title={s.title}>
              {s.title}
            </span>
            <span
              className="font-mono"
              style={{color: 'var(--color-th-muted-fg)'}}
            >
              {s.finalElo}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
