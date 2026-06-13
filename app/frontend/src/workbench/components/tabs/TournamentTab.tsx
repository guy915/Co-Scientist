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

import '@material/web/icon/icon.js';
import {useMemo} from 'react';
import type {Hypothesis, MatchRow} from '@/api/runs';
import {EloTrajectoryChart} from '../EloTrajectoryChart';

export function TournamentTab({
  matches,
  hypotheses,
}: {
  matches: MatchRow[];
  hypotheses: Hypothesis[];
}) {
  const byId = useMemo(
    () => Object.fromEntries(hypotheses.map(h => [h.id, h])),
    [hypotheses],
  );

  const leaderboard = useMemo(
    () =>
      [...hypotheses].sort((a, b) => b.elo_rating - a.elo_rating).slice(0, 10),
    [hypotheses],
  );

  if (!matches.length) {
    return (
      <div
        className="rounded border p-6 text-sm text-center"
        style={{
          borderColor: 'var(--md-sys-color-outline-variant)',
          color: 'var(--md-sys-color-on-surface-variant)',
        }}
      >
        Tournament matchups appear here after the ranking node runs.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <EloTrajectoryChart matches={matches} hypotheses={hypotheses} />

      <div className="grid lg:grid-cols-3 gap-4">
        <section className="lg:col-span-1 space-y-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide">
            Leaderboard
          </h2>
          <ol
            className="rounded border divide-y wb-fade-in"
            style={{
              borderColor: 'var(--md-sys-color-outline-variant)',
              backgroundColor: 'var(--md-sys-color-surface-container-low)',
            }}
          >
            {leaderboard.map((h, i) => {
              const total = h.win_count + h.loss_count;
              const winRate = total
                ? Math.round((h.win_count / total) * 100)
                : 0;
              return (
                <li
                  key={h.id}
                  className="grid grid-cols-[1.5rem_1fr_auto] items-start gap-x-2 gap-y-1 px-3 py-3 sm:flex sm:items-center sm:py-2"
                  style={{borderColor: 'var(--md-sys-color-outline-variant)'}}
                >
                  <span
                    className="font-mono text-xs text-right inline-flex items-center justify-end sm:w-6"
                    style={{color: 'var(--md-sys-color-on-surface-variant)'}}
                  >
                    {i === 0 ? (
                      // biome-ignore lint/a11y/noAriaHiddenOnFocusable: md-icon is a non-interactive decorative element
                      <md-icon style={{fontSize: '14px'}} aria-hidden="true">
                        emoji_events
                      </md-icon>
                    ) : (
                      i + 1
                    )}
                  </span>
                  <span className="min-w-0 text-sm font-medium leading-snug sm:flex-1 sm:truncate">
                    {h.title}
                  </span>
                  <span className="flex items-center gap-1">
                    {total > 0 && (
                      <span
                        className="text-[10px] font-mono px-1 py-0.5 rounded"
                        style={{
                          backgroundColor:
                            'color-mix(in srgb, var(--md-sys-color-tertiary) 18%, transparent)',
                          color: 'var(--md-sys-color-on-surface)',
                        }}
                        title={`${h.win_count} wins / ${h.loss_count} losses`}
                      >
                        {winRate}%
                      </span>
                    )}
                    <span
                      className="font-mono text-xs px-1.5 py-0.5 rounded"
                      style={{
                        backgroundColor:
                          'var(--md-sys-color-secondary-container)',
                      }}
                    >
                      {h.elo_rating}
                    </span>
                  </span>
                </li>
              );
            })}
          </ol>
        </section>

        <section className="lg:col-span-2 space-y-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide">
            Matchups{' '}
            <span style={{color: 'var(--md-sys-color-on-surface-variant)'}}>
              ({matches.length})
            </span>
          </h2>
          <ol className="space-y-1.5">
            {matches.map(m => {
              const w = byId[m.winner_id];
              const l = byId[m.loser_id];
              const wDelta = m.winner_elo_after - m.winner_elo_before;
              const lDelta = m.loser_elo_after - m.loser_elo_before;
              return (
                <li
                  key={m.id}
                  className="rounded border p-2 text-sm"
                  style={{
                    borderColor: 'var(--md-sys-color-outline-variant)',
                    backgroundColor:
                      'var(--md-sys-color-surface-container-low)',
                  }}
                >
                  <div className="space-y-2 sm:hidden">
                    <div className="flex items-center gap-2">
                      <span
                        className="shrink-0 text-[11px] font-mono px-1.5 py-0.5 rounded"
                        style={{
                          backgroundColor:
                            'var(--md-sys-color-secondary-container)',
                          color: 'var(--md-sys-color-on-secondary-container)',
                        }}
                      >
                        Iter {m.iteration}
                      </span>
                      <span
                        className="text-[10px] uppercase tracking-wide"
                        style={{
                          color: 'var(--md-sys-color-on-surface-variant)',
                        }}
                      >
                        Match result
                      </span>
                    </div>
                    <div
                      className="rounded-lg p-2.5"
                      style={{
                        backgroundColor:
                          'color-mix(in srgb, var(--md-sys-color-primary) 10%, transparent)',
                      }}
                    >
                      <div className="mb-1 flex items-center justify-between gap-2">
                        <span
                          className="text-[10px] font-semibold uppercase tracking-wide"
                          style={{color: 'var(--md-sys-color-primary)'}}
                        >
                          Winner
                        </span>
                        <span
                          className="font-mono text-xs"
                          title={`+${wDelta} Elo`}
                          style={{color: 'var(--md-sys-color-primary)'}}
                        >
                          {m.winner_elo_before} → {m.winner_elo_after}
                        </span>
                      </div>
                      <div className="font-medium leading-snug">
                        {w?.title ?? m.winner_id}
                      </div>
                    </div>
                    <div
                      className="rounded-lg p-2.5"
                      style={{
                        backgroundColor:
                          'color-mix(in srgb, var(--md-sys-color-error-container) 35%, transparent)',
                      }}
                    >
                      <div className="mb-1 flex items-center justify-between gap-2">
                        <span
                          className="text-[10px] font-semibold uppercase tracking-wide"
                          style={{color: 'var(--md-sys-color-error)'}}
                        >
                          Runner-up
                        </span>
                        <span
                          className="font-mono text-xs"
                          title={`${lDelta} Elo`}
                          style={{color: 'var(--md-sys-color-error)'}}
                        >
                          {m.loser_elo_before} → {m.loser_elo_after}
                        </span>
                      </div>
                      <div
                        className="leading-snug"
                        style={{
                          color: 'var(--md-sys-color-on-surface-variant)',
                        }}
                      >
                        {l?.title ?? m.loser_id}
                      </div>
                    </div>
                  </div>
                  <div className="hidden sm:flex sm:items-center sm:gap-2 sm:flex-wrap">
                    <span
                      className="shrink-0 text-[11px] font-mono px-1.5 py-0.5 rounded"
                      style={{
                        backgroundColor:
                          'var(--md-sys-color-secondary-container)',
                        color: 'var(--md-sys-color-on-secondary-container)',
                      }}
                    >
                      Iter {m.iteration}
                    </span>
                    <span className="flex-1 truncate font-medium">
                      {w?.title ?? m.winner_id}
                    </span>
                    <span
                      className="font-mono text-xs"
                      title={`+${wDelta} Elo`}
                      style={{color: 'var(--md-sys-color-primary)'}}
                    >
                      {m.winner_elo_before}{' '}
                      <md-icon
                        style={{fontSize: '12px', verticalAlign: 'middle'}}
                      >
                        arrow_forward
                      </md-icon>{' '}
                      {m.winner_elo_after}
                    </span>
                    <span
                      style={{color: 'var(--md-sys-color-on-surface-variant)'}}
                    >
                      ·
                    </span>
                    <span
                      className="flex-1 truncate"
                      style={{color: 'var(--md-sys-color-on-surface-variant)'}}
                    >
                      {l?.title ?? m.loser_id}
                    </span>
                    <span
                      className="font-mono text-xs"
                      title={`${lDelta} Elo`}
                      style={{color: 'var(--md-sys-color-error)'}}
                    >
                      {m.loser_elo_before}{' '}
                      <md-icon
                        style={{fontSize: '12px', verticalAlign: 'middle'}}
                      >
                        arrow_forward
                      </md-icon>{' '}
                      {m.loser_elo_after}
                    </span>
                  </div>
                  {m.rationale && (
                    <p
                      className="text-xs mt-2 leading-relaxed"
                      style={{color: 'var(--md-sys-color-on-surface-variant)'}}
                    >
                      {m.rationale}
                    </p>
                  )}
                </li>
              );
            })}
          </ol>
        </section>
      </div>
    </div>
  );
}
