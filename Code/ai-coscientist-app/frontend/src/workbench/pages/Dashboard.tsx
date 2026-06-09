import { Beaker, Plus, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  getRun,
  getSystemStatus,
  listRuns,
  type Run,
  type RunStatus,
  type RunSummary,
  type SystemStatus,
} from "@/api/runs";
import { RunStatusPill } from "../components/RunStatusPill";

function fmtDate(ts: number) {
  return new Date(ts * 1000).toLocaleString();
}

function fmtRelative(ts: number) {
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

type Filter = "all" | RunStatus;

export function Dashboard() {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [summaries, setSummaries] = useState<Record<string, RunSummary>>({});
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");

  useEffect(() => {
    void getSystemStatus()
      .then(setSystemStatus)
      .catch(() => {});
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const r = await listRuns();
        if (cancelled) return;
        setRuns(r);
        // Fan-out the per-run summary fetches; tolerate failures.
        const entries = await Promise.allSettled(
          r.slice(0, 30).map(async (run) => {
            const detail = await getRun(run.id);
            return [run.id, detail.summary] as const;
          })
        );
        if (cancelled) return;
        const map: Record<string, RunSummary> = {};
        for (const e of entries) {
          if (e.status === "fulfilled") map[e.value[0]] = e.value[1];
        }
        setSummaries(map);
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const filtered = useMemo(() => {
    if (!runs) return null;
    return runs.filter((r) => {
      if (filter !== "all" && r.status !== filter) return false;
      if (!query.trim()) return true;
      return r.research_goal.toLowerCase().includes(query.toLowerCase());
    });
  }, [runs, query, filter]);

  const totals = useMemo(() => {
    if (!runs) return null;
    return {
      total: runs.length,
      completed: runs.filter((r) => r.status === "completed").length,
      running: runs.filter((r) => ["running", "queued", "synthesizing"].includes(r.status)).length,
      mock: runs.filter((r) => r.provider === "mock").length,
      hypotheses: Object.values(summaries).reduce((acc, s) => acc + (s?.hypotheses ?? 0), 0),
      matches: Object.values(summaries).reduce((acc, s) => acc + (s?.matches ?? 0), 0),
    };
  }, [runs, summaries]);

  return (
    <div className="space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Research runs</h1>
          <p className="text-sm" style={{ color: "var(--color-th-muted-fg)" }}>
            Hypothesis-generation workspace. Each run is durable, replayable, and reopenable.
          </p>
        </div>
        <Link
          to="/runs/new"
          className="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm transition-opacity hover:opacity-90"
          style={{
            backgroundColor: "var(--color-th-primary)",
            color: "var(--color-th-primary-fg)",
          }}
        >
          <Plus className="w-4 h-4" aria-hidden="true" />
          New run
        </Link>
      </header>

      {totals && (
        <section className="grid grid-cols-2 sm:grid-cols-4 gap-2 wb-fade-in">
          <StatCard label="Total runs" value={totals.total} sub={`${totals.completed} completed`} />
          <StatCard
            label="Active"
            value={totals.running}
            sub={totals.running ? "in progress" : "no runs in progress"}
          />
          <StatCard
            label="Hypotheses generated"
            value={totals.hypotheses}
            sub={`${totals.matches} matches`}
          />
          <StatCard
            label="Current mode"
            value={systemStatus ? systemStatus.provider : "…"}
            sub={
              systemStatus
                ? systemStatus.mock_mode
                  ? "no LLM key set"
                  : systemStatus.model_name
                : undefined
            }
          />
        </section>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <div
          className="flex items-center gap-2 px-2.5 py-1.5 rounded border flex-1 min-w-[16rem]"
          style={{ borderColor: "var(--color-th-input)", backgroundColor: "var(--color-th-bg)" }}
        >
          <Search
            className="w-4 h-4"
            style={{ color: "var(--color-th-muted-fg)" }}
            aria-hidden="true"
          />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by research goal…"
            className="flex-1 bg-transparent outline-none text-sm"
            aria-label="Search runs"
          />
        </div>
        <div className="flex gap-1 text-sm">
          {(["all", "completed", "running", "failed", "blocked"] as Filter[]).map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => setFilter(f)}
              className="px-2 py-1.5 rounded border capitalize transition-colors"
              style={{
                borderColor: filter === f ? "var(--color-th-primary)" : "var(--color-th-border)",
                backgroundColor: filter === f ? "var(--color-th-secondary)" : "transparent",
                fontWeight: filter === f ? 600 : 400,
              }}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div
          role="alert"
          className="rounded border p-3 text-sm"
          style={{
            borderColor: "var(--color-th-destructive)",
            color: "var(--color-th-destructive)",
          }}
        >
          {error}
        </div>
      )}

      {runs === null && !error && <Skeleton />}

      {runs && runs.length === 0 && (
        <div
          className="rounded border p-8 text-center wb-fade-in"
          style={{ borderColor: "var(--color-th-border)" }}
        >
          <Beaker
            className="w-8 h-8 mx-auto mb-3"
            style={{ color: "var(--color-th-muted-fg)" }}
            aria-hidden="true"
          />
          <p className="font-medium">No runs yet</p>
          <p className="text-sm mb-4" style={{ color: "var(--color-th-muted-fg)" }}>
            Start with a research goal to generate, debate, and rank hypotheses.
          </p>
          <Link
            to="/runs/new"
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm transition-opacity hover:opacity-90"
            style={{
              backgroundColor: "var(--color-th-primary)",
              color: "var(--color-th-primary-fg)",
            }}
          >
            Create your first run
          </Link>
        </div>
      )}

      {filtered && filtered.length === 0 && runs && runs.length > 0 && (
        <div
          className="rounded border p-8 text-center text-sm"
          style={{ borderColor: "var(--color-th-border)", color: "var(--color-th-muted-fg)" }}
        >
          No runs match your filter.
        </div>
      )}

      {filtered && filtered.length > 0 && (
        <div
          className="rounded border overflow-hidden wb-fade-in"
          style={{
            borderColor: "var(--color-th-border)",
            backgroundColor: "var(--color-th-card)",
          }}
        >
          <table className="w-full text-sm">
            <thead style={{ backgroundColor: "var(--color-th-secondary)" }}>
              <tr className="text-left">
                <th className="px-4 py-2 font-semibold">Research goal</th>
                <th className="px-4 py-2 font-semibold w-24">Profile</th>
                <th className="px-4 py-2 font-semibold w-32">Status</th>
                <th className="px-4 py-2 font-semibold w-24">Provider</th>
                <th className="px-4 py-2 font-semibold w-24">Ideas</th>
                <th className="px-4 py-2 font-semibold w-32" title="Created">
                  Created
                </th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => (
                <tr
                  key={r.id}
                  className="border-t transition-colors hover:bg-[color:var(--color-th-secondary)]"
                  style={{ borderColor: "var(--color-th-border)" }}
                >
                  <td className="px-4 py-2">
                    <Link
                      to={`/runs/${r.id}`}
                      className="font-medium underline-offset-2 hover:underline"
                    >
                      {r.research_goal}
                    </Link>
                  </td>
                  <td className="px-4 py-2 capitalize">{r.profile}</td>
                  <td className="px-4 py-2">
                    <RunStatusPill status={r.status} />
                  </td>
                  <td className="px-4 py-2 capitalize">{r.provider}</td>
                  <td className="px-4 py-2" style={{ color: "var(--color-th-muted-fg)" }}>
                    {summaries[r.id]?.hypotheses ?? "—"}
                  </td>
                  <td
                    className="px-4 py-2"
                    style={{ color: "var(--color-th-muted-fg)" }}
                    title={fmtDate(r.created_at)}
                  >
                    {fmtRelative(r.created_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function StatCard({ label, value, sub }: { label: string; value: number | string; sub?: string }) {
  return (
    <div
      className="rounded border p-3"
      style={{
        borderColor: "var(--color-th-border)",
        backgroundColor: "var(--color-th-card)",
      }}
    >
      <div
        className="text-xs uppercase tracking-wide"
        style={{ color: "var(--color-th-muted-fg)" }}
      >
        {label}
      </div>
      <div className="text-2xl font-semibold mt-1">{value}</div>
      {sub && (
        <div className="text-xs mt-0.5" style={{ color: "var(--color-th-muted-fg)" }}>
          {sub}
        </div>
      )}
    </div>
  );
}

function Skeleton() {
  return (
    <div className="space-y-2" aria-busy="true">
      {[...Array(4)].map((_, i) => (
        <div key={i} className="wb-skeleton h-10" />
      ))}
    </div>
  );
}
