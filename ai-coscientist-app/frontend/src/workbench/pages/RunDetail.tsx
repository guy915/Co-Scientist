import "@material/web/button/outlined-button.js";
import "@material/web/button/text-button.js";
import "@material/web/icon/icon.js";
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
import { MdSecondaryTabs } from "@/md3/MdTabs";
import { IdeaModal } from "../components/IdeaModal";
import { RunStatusPill } from "../components/RunStatusPill";
import { EvidenceTab } from "../components/tabs/EvidenceTab";
import { IdeasTab } from "../components/tabs/IdeasTab";
import { OverviewTab } from "../components/tabs/OverviewTab";
import { ReportTab } from "../components/tabs/ReportTab";
import { TournamentTab } from "../components/tabs/TournamentTab";

const TABS = ["overview", "ideas", "evidence", "tournament", "report"] as const;
type TabName = (typeof TABS)[number];

const TAB_ICON_NAMES: Record<TabName, string> = {
  overview: "monitoring",
  ideas: "format_list_numbered",
  evidence: "menu_book",
  tournament: "compare_arrows",
  report: "description",
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

  const onTabChange = useCallback(
    (index: number) => {
      const t = TABS[index];
      if (t) navigate(`/runs/${id}/${t === "overview" ? "" : t}`);
    },
    [id, navigate]
  );

  if (!id) return null;

  const isLiveActive = isOpen && !terminal;

  const tabList = TABS.map((t) => ({
    label: t,
    icon: TAB_ICON_NAMES[t],
  }));

  const activeTabIndex = TABS.indexOf(activeTab);

  return (
    <div className="space-y-4">
      <header className="space-y-3">
        <Link
          to="/"
          className="inline-flex items-center gap-1 text-sm hover:underline"
          style={{ color: "var(--md-sys-color-on-surface-variant)" }}
        >
          {/* biome-ignore lint/a11y/noAriaHiddenOnFocusable: md-icon is a non-interactive decorative element */}
          <md-icon aria-hidden="true" style={{ fontSize: "14px" }}>
            arrow_back
          </md-icon>{" "}
          All runs
        </Link>
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="space-y-1 min-w-0 flex-1">
            <h1 className="md-typescale-headline-medium text-2xl font-semibold tracking-tight">
              {run?.research_goal ?? "Loading…"}
            </h1>
            <div
              className="flex items-center gap-2 text-sm flex-wrap"
              style={{ color: "var(--md-sys-color-on-surface-variant)" }}
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
            <md-outlined-button onclick={(() => void refresh()) as EventListener}>
              {/* biome-ignore lint/a11y/noAriaHiddenOnFocusable: md-icon is a non-interactive decorative element */}
              <md-icon slot="icon" aria-hidden="true">
                refresh
              </md-icon>
              Refresh
            </md-outlined-button>
            {run?.status === "running" || run?.status === "queued" ? (
              <md-outlined-button
                onclick={(() => void onCancel()) as EventListener}
                style={
                  {
                    "--md-outlined-button-outline-color": "var(--md-sys-color-error)",
                    "--md-outlined-button-label-text-color": "var(--md-sys-color-error)",
                  } as React.CSSProperties
                }
              >
                {/* biome-ignore lint/a11y/noAriaHiddenOnFocusable: md-icon is a non-interactive decorative element */}
                <md-icon slot="icon" aria-hidden="true">
                  stop
                </md-icon>
                Cancel
              </md-outlined-button>
            ) : null}
            {report && (
              <md-outlined-button
                onclick={
                  (() => {
                    const a = document.createElement("a");
                    a.href = reportMarkdownUrl(id);
                    a.download = "report.md";
                    a.click();
                  }) as EventListener
                }
              >
                {/* biome-ignore lint/a11y/noAriaHiddenOnFocusable: md-icon is a non-interactive decorative element */}
                <md-icon slot="icon" aria-hidden="true">
                  download
                </md-icon>
                Export report.md
              </md-outlined-button>
            )}
          </div>
        </div>
      </header>

      <MdSecondaryTabs tabs={tabList} activeIndex={activeTabIndex} onChange={onTabChange} />

      {error && (
        <div
          role="alert"
          className="text-sm rounded border p-2"
          style={{
            borderColor: "var(--md-sys-color-error)",
            color: "var(--md-sys-color-error)",
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
        // biome-ignore lint/a11y/useSemanticElements: role="status" is a live region; <output> has different semantics
        <div
          role="status"
          className="fixed bottom-4 right-4 z-50 rounded border px-3 py-2 text-sm shadow-lg wb-fade-in"
          style={{
            borderColor:
              toast.type === "error"
                ? "var(--md-sys-color-error)"
                : "var(--md-sys-color-outline-variant)",
            backgroundColor: "var(--md-sys-color-surface-container)",
            color: "var(--md-sys-color-on-surface)",
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
        {["sk-a", "sk-b", "sk-c", "sk-d"].map((k) => (
          <div key={k} className="wb-skeleton h-24" />
        ))}
      </div>
      <div className="wb-skeleton h-48 w-full" />
    </div>
  );
}
