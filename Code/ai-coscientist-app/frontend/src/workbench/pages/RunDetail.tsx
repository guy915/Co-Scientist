import {
  Activity,
  ArrowLeft,
  Book,
  Download,
  FileText,
  ListOrdered,
  RefreshCcw,
  Square,
  Swords,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  type CitationRow,
  cancelRun,
  type Evidence,
  getCitations,
  getEvidence,
  getHypotheses,
  getMatches,
  getReport,
  getReviews,
  getRun,
  getSafety,
  type Hypothesis,
  type MatchRow,
  type Report,
  type Review,
  type RunWithSummary,
  reportMarkdownUrl,
  type SafetyDecision,
} from "@/api/runs";
import { type StreamEvent, useRunStream } from "@/hooks/useRunStream";
import { IdeaModal } from "../components/IdeaModal";
import { RunStatusPill } from "../components/RunStatusPill";
import { EvidenceTab } from "../components/tabs/EvidenceTab";
import { IdeasTab } from "../components/tabs/IdeasTab";
import { OverviewTab } from "../components/tabs/OverviewTab";
import { ReportTab } from "../components/tabs/ReportTab";
import { TournamentTab } from "../components/tabs/TournamentTab";

const TABS = ["overview", "ideas", "evidence", "tournament", "report"] as const;
type TabName = (typeof TABS)[number];

const TAB_ICONS: Record<TabName, typeof Activity> = {
  overview: Activity,
  ideas: ListOrdered,
  evidence: Book,
  tournament: Swords,
  report: FileText,
};

export function RunDetail() {
  const { id, tab } = useParams<{ id: string; tab?: string }>();
  const navigate = useNavigate();
  const activeTab = (
    tab && (TABS as readonly string[]).includes(tab) ? tab : "overview"
  ) as TabName;

  const [run, setRun] = useState<RunWithSummary | null>(null);
  const [hypotheses, setHypotheses] = useState<Hypothesis[]>([]);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [matches, setMatches] = useState<MatchRow[]>([]);
  const [reviews, setReviews] = useState<Review[]>([]);
  const [safety, setSafety] = useState<SafetyDecision[]>([]);
  const [citations, setCitations] = useState<CitationRow[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [focusedHypId, setFocusedHypId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [toast, setToast] = useState<{ type: "info" | "error"; message: string } | null>(null);

  const { events, terminal, isOpen } = useRunStream(id ?? null, 0);

  const refresh = useCallback(async () => {
    if (!id) return;
    try {
      const [r, h, e, m, rv, s, c, rep] = await Promise.all([
        getRun(id),
        getHypotheses(id),
        getEvidence(id),
        getMatches(id),
        getReviews(id),
        getSafety(id),
        getCitations(id),
        getReport(id),
      ]);
      setRun(r);
      setHypotheses(h);
      setEvidence(e);
      setMatches(m);
      setReviews(rv);
      setSafety(s);
      setCitations(c);
      setReport(rep);
      setLoaded(true);
      setError(null);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
      setLoaded(true);
    }
  }, [id]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Re-pull on new events so tabs stay in sync.
  useEffect(() => {
    if (!events.length) return;
    const interesting = events[events.length - 1]?.type;
    if (interesting && interesting !== "status") void refresh();
  }, [events, refresh]);

  useEffect(() => {
    if (terminal) void refresh();
  }, [terminal, refresh]);

  // Toast on terminal status.
  useEffect(() => {
    if (!terminal || !run) return;
    if (run.status === "completed") {
      setToast({ type: "info", message: "Run completed." });
      const t = setTimeout(() => setToast(null), 3000);
      return () => clearTimeout(t);
    }
    if (run.status === "failed" || run.status === "blocked") {
      setToast({ type: "error", message: `Run ${run.status}${run.error ? `: ${run.error}` : ""}` });
    }
  }, [terminal, run]);

  const onCancel = useCallback(async () => {
    if (!id) return;
    try {
      await cancelRun(id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [id, refresh]);

  const focusedHypothesis = useMemo(
    () => hypotheses.find((h) => h.id === focusedHypId) || null,
    [hypotheses, focusedHypId]
  );

  if (!id) return null;

  const isLiveActive = isOpen && !terminal;

  return (
    <div className="space-y-4">
      <header className="space-y-3">
        <Link
          to="/"
          className="inline-flex items-center gap-1 text-sm hover:underline"
          style={{ color: "var(--color-th-muted-fg)" }}
        >
          <ArrowLeft className="w-3.5 h-3.5" aria-hidden="true" /> All runs
        </Link>
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="space-y-1 min-w-0 flex-1">
            <h1 className="text-2xl font-semibold tracking-tight">
              {run?.research_goal ?? "Loading…"}
            </h1>
            <div
              className="flex items-center gap-2 text-sm flex-wrap"
              style={{ color: "var(--color-th-muted-fg)" }}
            >
              {run && <RunStatusPill status={run.status} />}
              {run && (
                <span>
                  · profile: <strong className="capitalize">{run.profile}</strong>
                </span>
              )}
              {run && (
                <span>
                  · provider: <strong className="capitalize">{run.provider}</strong>
                </span>
              )}
              {isLiveActive && (
                <span className="inline-flex items-center gap-1" aria-live="polite">
                  · <span className="wb-live-dot" aria-hidden="true" /> live
                </span>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void refresh()}
              className="inline-flex items-center gap-1 text-xs px-2.5 py-1.5 rounded border transition-colors hover:bg-[color:var(--color-th-secondary)]"
              style={{ borderColor: "var(--color-th-border)" }}
            >
              <RefreshCcw className="w-3.5 h-3.5" aria-hidden="true" /> Refresh
            </button>
            {run?.status === "running" || run?.status === "queued" ? (
              <button
                type="button"
                onClick={() => void onCancel()}
                className="inline-flex items-center gap-1 text-xs px-2.5 py-1.5 rounded border transition-colors hover:bg-[color:var(--color-th-secondary)]"
                style={{
                  borderColor: "var(--color-th-destructive)",
                  color: "var(--color-th-destructive)",
                }}
              >
                <Square className="w-3.5 h-3.5" aria-hidden="true" /> Cancel
              </button>
            ) : null}
            {report && (
              <a
                href={reportMarkdownUrl(id)}
                className="inline-flex items-center gap-1 text-xs px-2.5 py-1.5 rounded border transition-colors hover:bg-[color:var(--color-th-secondary)]"
                style={{ borderColor: "var(--color-th-border)" }}
                download
              >
                <Download className="w-3.5 h-3.5" aria-hidden="true" /> Export report.md
              </a>
            )}
          </div>
        </div>
      </header>

      <nav
        className="border-b flex gap-1 text-sm overflow-x-auto"
        style={{ borderColor: "var(--color-th-border)" }}
        role="tablist"
      >
        {TABS.map((t) => {
          const Icon = TAB_ICONS[t];
          const count =
            t === "ideas"
              ? hypotheses.length
              : t === "evidence"
                ? evidence.length
                : t === "tournament"
                  ? matches.length
                  : 0;
          return (
            <button
              key={t}
              role="tab"
              aria-selected={t === activeTab}
              type="button"
              onClick={() => navigate(`/runs/${id}/${t === "overview" ? "" : t}`)}
              className="px-3 py-2 -mb-px border-b-2 capitalize inline-flex items-center gap-1.5 transition-colors"
              style={{
                borderColor: t === activeTab ? "var(--color-th-primary)" : "transparent",
                fontWeight: t === activeTab ? 600 : 400,
                color: t === activeTab ? "var(--color-th-fg)" : "var(--color-th-muted-fg)",
              }}
            >
              <Icon className="w-3.5 h-3.5" aria-hidden="true" />
              {t}
              {count > 0 && (
                <span
                  className="ml-1 text-xs px-1.5 py-0.5 rounded font-mono"
                  style={{
                    backgroundColor: "var(--color-th-secondary)",
                    color: "var(--color-th-secondary-fg)",
                  }}
                >
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </nav>

      {error && (
        <div
          role="alert"
          className="text-sm rounded border p-2"
          style={{
            borderColor: "var(--color-th-destructive)",
            color: "var(--color-th-destructive)",
          }}
        >
          {error}
        </div>
      )}

      {!loaded && !error ? (
        <RunDetailSkeleton />
      ) : (
        <div className="wb-fade-in" key={activeTab}>
          {activeTab === "overview" && (
            <OverviewTab
              run={run}
              hypotheses={hypotheses}
              evidence={evidence}
              matches={matches}
              safety={safety}
              events={events as StreamEvent[]}
            />
          )}
          {activeTab === "ideas" && (
            <IdeasTab
              hypotheses={hypotheses}
              citations={citations}
              reviews={reviews}
              onFocus={setFocusedHypId}
            />
          )}
          {activeTab === "evidence" && <EvidenceTab evidence={evidence} citations={citations} />}
          {activeTab === "tournament" && (
            <TournamentTab matches={matches} hypotheses={hypotheses} />
          )}
          {activeTab === "report" && <ReportTab runId={id} report={report} safety={safety} />}
        </div>
      )}

      {focusedHypothesis && (
        <IdeaModal
          hypothesis={focusedHypothesis}
          allHypotheses={hypotheses}
          reviews={reviews.filter((r) => r.hypothesis_id === focusedHypothesis.id)}
          citations={citations.filter((c) => c.hypothesis_id === focusedHypothesis.id)}
          evidence={evidence}
          onClose={() => setFocusedHypId(null)}
        />
      )}

      {toast && (
        <div
          role="status"
          className="fixed bottom-4 right-4 z-50 rounded border px-3 py-2 text-sm shadow-lg wb-fade-in"
          style={{
            borderColor:
              toast.type === "error" ? "var(--color-th-destructive)" : "var(--color-th-border)",
            backgroundColor: "var(--color-th-card)",
            color: "var(--color-th-fg)",
          }}
        >
          {toast.message}
        </div>
      )}
    </div>
  );
}

function RunDetailSkeleton() {
  return (
    <div className="space-y-3" aria-busy="true">
      <div className="wb-skeleton h-32 w-full" />
      <div className="grid grid-cols-4 gap-2">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="wb-skeleton h-24" />
        ))}
      </div>
      <div className="wb-skeleton h-48 w-full" />
    </div>
  );
}
