import "@material/web/icon/icon.js";
import { useMemo } from "react";
import type { Hypothesis, MatchRow } from "@/api/runs";
import { EloTrajectoryChart } from "../EloTrajectoryChart";

export function TournamentTab({
  matches,
  hypotheses,
}: {
  matches: MatchRow[];
  hypotheses: Hypothesis[];
}) {
  const byId = useMemo(() => Object.fromEntries(hypotheses.map((h) => [h.id, h])), [hypotheses]);

  const leaderboard = useMemo(
    () => [...hypotheses].sort((a, b) => b.elo_rating - a.elo_rating).slice(0, 10),
    [hypotheses]
  );

  if (!matches.length) {
    return (
      <div
        className="rounded border p-6 text-sm text-center"
        style={{
          borderColor: "var(--md-sys-color-outline-variant)",
          color: "var(--md-sys-color-on-surface-variant)",
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
          <h2 className="text-sm font-semibold uppercase tracking-wide">Leaderboard</h2>
          <ol
            className="rounded border divide-y wb-fade-in"
            style={{
              borderColor: "var(--md-sys-color-outline-variant)",
              backgroundColor: "var(--md-sys-color-surface-container-low)",
            }}
          >
            {leaderboard.map((h, i) => {
              const total = h.win_count + h.loss_count;
              const winRate = total ? Math.round((h.win_count / total) * 100) : 0;
              return (
                <li
                  key={h.id}
                  className="px-3 py-2 flex items-center gap-2"
                  style={{ borderColor: "var(--md-sys-color-outline-variant)" }}
                >
                  <span
                    className="font-mono text-xs w-6 text-right inline-flex items-center justify-end"
                    style={{ color: "var(--md-sys-color-on-surface-variant)" }}
                  >
                    {i === 0 ? (
                      // biome-ignore lint/a11y/noAriaHiddenOnFocusable: md-icon is a non-interactive decorative element
                      <md-icon style={{ fontSize: "14px" }} aria-hidden="true">
                        emoji_events
                      </md-icon>
                    ) : (
                      i + 1
                    )}
                  </span>
                  <span className="flex-1 truncate text-sm">{h.title}</span>
                  {total > 0 && (
                    <span
                      className="text-[10px] font-mono px-1 py-0.5 rounded"
                      style={{
                        backgroundColor:
                          "color-mix(in srgb, var(--md-sys-color-tertiary) 18%, transparent)",
                        color: "var(--md-sys-color-on-surface)",
                      }}
                      title={`${h.win_count} wins / ${h.loss_count} losses`}
                    >
                      {winRate}%
                    </span>
                  )}
                  <span
                    className="font-mono text-xs px-1.5 py-0.5 rounded"
                    style={{
                      backgroundColor: "var(--md-sys-color-secondary-container)",
                    }}
                  >
                    {h.elo_rating}
                  </span>
                </li>
              );
            })}
          </ol>
        </section>

        <section className="lg:col-span-2 space-y-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide">
            Matchups{" "}
            <span style={{ color: "var(--md-sys-color-on-surface-variant)" }}>
              ({matches.length})
            </span>
          </h2>
          <ol className="space-y-1.5">
            {matches.map((m) => {
              const w = byId[m.winner_id];
              const l = byId[m.loser_id];
              const wDelta = m.winner_elo_after - m.winner_elo_before;
              const lDelta = m.loser_elo_after - m.loser_elo_before;
              return (
                <li
                  key={m.id}
                  className="rounded border p-2 text-sm"
                  style={{
                    borderColor: "var(--md-sys-color-outline-variant)",
                    backgroundColor: "var(--md-sys-color-surface-container-low)",
                  }}
                >
                  <div className="flex items-center gap-2 flex-wrap">
                    <span
                      className="text-[11px] font-mono px-1.5 py-0.5 rounded"
                      style={{
                        backgroundColor: "var(--md-sys-color-secondary-container)",
                        color: "var(--md-sys-color-on-secondary-container)",
                      }}
                    >
                      Iter {m.iteration}
                    </span>
                    <span className="flex-1 truncate font-medium">{w?.title ?? m.winner_id}</span>
                    <span
                      className="font-mono text-xs"
                      title={`+${wDelta} Elo`}
                      style={{ color: "var(--md-sys-color-primary)" }}
                    >
                      {m.winner_elo_before}{" "}
                      <md-icon style={{ fontSize: "12px", verticalAlign: "middle" }}>
                        arrow_forward
                      </md-icon>{" "}
                      {m.winner_elo_after}
                    </span>
                    <span style={{ color: "var(--md-sys-color-on-surface-variant)" }}>·</span>
                    <span
                      className="flex-1 truncate"
                      style={{ color: "var(--md-sys-color-on-surface-variant)" }}
                    >
                      {l?.title ?? m.loser_id}
                    </span>
                    <span
                      className="font-mono text-xs"
                      title={`${lDelta} Elo`}
                      style={{ color: "var(--md-sys-color-error)" }}
                    >
                      {m.loser_elo_before}{" "}
                      <md-icon style={{ fontSize: "12px", verticalAlign: "middle" }}>
                        arrow_forward
                      </md-icon>{" "}
                      {m.loser_elo_after}
                    </span>
                  </div>
                  {m.rationale && (
                    <p
                      className="text-xs mt-1"
                      style={{ color: "var(--md-sys-color-on-surface-variant)" }}
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
