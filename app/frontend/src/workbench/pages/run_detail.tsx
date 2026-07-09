import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {Link, useNavigate, useParams} from 'react-router-dom';
import {
  type Evidence,
  getEvidence,
  getHypotheses,
  getMatches,
  getReport,
  getReviews,
  getRun,
  type Hypothesis,
  type MatchRow,
  type Report,
  type ReportPayload,
  type ResearchOverview,
  type Review,
  runGoal,
  type RunWithSummary,
} from '@/api/runs';
import {Icon, type IconName} from '@/components/icon';
import {useDebouncedCallback} from '@/hooks/use_debounced_callback';
import {type StreamEvent, useRunStream} from '@/hooks/use_run_stream';
import {isLiverFibrosisGoal} from '@/lib/demo_domains';
import {formatDurationPhrase} from '@/lib/duration';
import {sortByEloDesc} from '@/lib/hypotheses';
import {TruncatedLabel} from '../components/truncated_label';
import {IdeasTab} from '../components/tabs/ideas_tab';
import {
  REPORT_H3_CLASSES,
  REPORT_H4_CLASSES,
  REPORT_LIST_CLASSES,
  REPORT_SECTION_CLASSES,
  REPORT_SECTION_LIST_ITEM_CLASSES,
  REPORT_SECTION_LIST_META_CLASSES,
  ReportDocument,
  ReportList,
} from './run_detail_document';
import {LearningView} from './run_detail_learning';

// Canonical tab route segments, in the order the nav bar renders them.
const TABS = ['details', 'learning', 'overview', 'ideas'] as const;
type TabName = (typeof TABS)[number];

// Material icon shown per tab in the nav bar (keyed by TabName so a missing
// entry is a compile error, not a silent blank icon).
const TAB_ICON_NAMES: Record<TabName, IconName> = {
  details: 'assignment',
  learning: 'menu_book',
  overview: 'summarize',
  ideas: 'lightbulb',
};

// Human-readable label shown per tab in the nav bar.
const TAB_LABELS: Record<TabName, string> = {
  details: 'Goal Details',
  learning: 'Learning',
  overview: 'Research Overview',
  ideas: 'All Ideas',
};

const REPORT_PAGE_CLASSES =
  'cosci-report-page grid h-full min-h-0 ' +
  'grid-rows-[3.75rem_5rem_minmax(0,1fr)] bg-cosci-bg text-cosci-fg ' +
  'max-[720px]:min-w-0 max-[720px]:overflow-hidden';

const REPORT_TITLEBAR_CLASSES =
  'cosci-report-titlebar flex min-w-0 items-center justify-between gap-6 ' +
  'border-b border-cosci-border px-9 max-[720px]:gap-[0.35rem] ' +
  'max-[720px]:px-[0.7rem]';

const REPORT_TITLE_LEFT_CLASSES =
  'cosci-report-title-left flex min-w-0 items-center gap-4 ' +
  'max-[720px]:gap-[0.45rem]';

const REPORT_BACK_CLASSES =
  'cosci-report-back grid h-10 w-10 shrink-0 ' +
  'place-items-center rounded-full text-cosci-muted ' +
  'no-underline hover:bg-cosci-hover';

const REPORT_TITLE_CLASSES =
  'm-0 min-w-0 overflow-hidden text-[1.2rem] leading-[1.25] ' +
  'font-normal tracking-normal max-[720px]:text-[0.9rem]';

const REPORT_TITLE_TEXT_CLASSES =
  'block min-w-0 overflow-hidden whitespace-nowrap';

const REPORT_TABS_CLASSES =
  'reference-report-tabs grid grid-cols-4 border-b border-cosci-border ' +
  'max-[720px]:min-w-0 max-[720px]:overflow-x-hidden';

const REPORT_TAB_BUTTON_BASE_CLASSES =
  'relative grid min-w-0 cursor-pointer content-center justify-items-center ' +
  'gap-[0.35rem] border-0 bg-transparent font-[inherit] text-sm ' +
  'max-[720px]:gap-[0.2rem] max-[720px]:text-[0.68rem]';

const REPORT_TAB_SELECTED_CLASSES =
  'text-cosci-blue after:absolute after:right-[1.1rem] after:bottom-0 ' +
  'after:left-[1.1rem] after:h-[0.18rem] after:rounded-t-full ' +
  "after:bg-cosci-blue-strong after:content-['']";

const REPORT_TAB_ICON_CLASSES = 'text-[1.35rem] max-[720px]:text-[1.12rem]';

const REPORT_TAB_LABEL_CLASSES = 'max-[720px]:text-[0.75rem]';

const REPORT_SCROLL_CLASSES =
  'cosci-report-scroll min-h-0 overflow-auto max-[720px]:overflow-x-hidden';

const REPORT_ALERT_CLASSES =
  'cosci-report-alert mx-8 mt-4 rounded-xl border border-cosci-danger-border ' +
  'bg-cosci-danger-bg px-4 py-3 text-cosci-danger-fg';

const REPORT_TOAST_CLASSES =
  'reference-report-toast fixed right-4 bottom-4 z-50 rounded-xl border ' +
  'border-cosci-danger-border bg-cosci-danger-bg px-4 py-3 ' +
  'text-cosci-danger-fg';

const REPORT_SKELETON_CLASSES =
  'cosci-report-skeleton mx-auto my-9 grid w-[min(100%_-_3rem,58rem)] gap-4 ' +
  'max-[720px]:mt-5 max-[720px]:mb-12 ' +
  'max-[720px]:w-[min(100%_-_1.2rem,100%)] max-[720px]:max-w-none';

const ALL_IDEAS_CLASSES = 'cosci-all-ideas h-full p-0';

const REPORT_LEAD_STAT_CLASSES =
  'cosci-overview-lead-stat mt-1 mb-4 text-cosci-fg';

// Legacy/alternate route segments that resolve to a canonical TabName, so old
// links (or a stray typo) still land on a real tab instead of 404-ing.
const TAB_ALIASES: Record<string, TabName> = {
  specifications: 'details',
  specs: 'details',
  knowledge: 'learning',
  evidence: 'learning',
  summary: 'overview',
  report: 'overview',
  hypotheses: 'ideas',
};

type RunDataKey = 'hypotheses' | 'evidence' | 'matches' | 'reviews' | 'report';

// Which fetched collections each canonical event type can change mid-run.
// Event types not listed (supervisor.plan, research_overview, safety.*, ...)
// only affect the run row itself, which every refresh re-reads; the terminal
// full refresh is the safety net for anything persisted only at finalize.
const EVENT_DATA_KEYS: Record<string, readonly RunDataKey[]> = {
  literature_review: ['evidence'],
  generate: ['hypotheses'],
  reflection: ['reviews'],
  review: ['reviews'],
  meta_review: ['reviews'],
  deep_verification: ['reviews'],
  proximity: ['hypotheses'],
  ranking: ['hypotheses', 'matches'],
  evolve: ['hypotheses'],
  report: ['report'],
};

// Collects the RunDataKey set a batch of newly-arrived events touches
// (multiple event types can map to the same key; see EVENT_DATA_KEYS).
function dataKeysFromEvents(events: readonly StreamEvent[]): Set<RunDataKey> {
  const keys = new Set<RunDataKey>();
  for (const event of events) {
    for (const key of EVENT_DATA_KEYS[event.type] ?? []) keys.add(key);
  }
  return keys;
}

// Tab-switch handling: navigates to the new tab route, and (special case)
// bumps ideasViewKey when "All Ideas" is re-tapped while already active so
// IdeasTab remounts and resets its mobile master-detail selection back to
// the list (that view has no back button of its own — see MobileIdeaView).
function useTabNavigation(id: string | undefined, activeTab: TabName) {
  const navigate = useNavigate();
  // Bumped when "All Ideas" is re-tapped, remounting IdeasTab to reset its
  // mobile master-detail selection back to the list.
  const [ideasViewKey, setIdeasViewKey] = useState(0);

  const onTabChange = useCallback(
    (nextTab: TabName) => {
      if (!id) return;
      if (nextTab === 'ideas' && activeTab === 'ideas') {
        setIdeasViewKey(key => key + 1);
      }
      // Always include the tab (details included) so every tab is the same
      // required-param route — switching tabs never remounts RunDetail.
      void navigate(`/runs/${id}/${nextTab}`);
    },
    [id, navigate, activeTab],
  );

  return {ideasViewKey, onTabChange};
}

/**
 * Renders the Co-Scientist goal report surface from the reference footage.
 */
export function RunDetail() {
  const {id, tab} = useParams<{id: string; tab?: string}>();
  const activeTab = normalizeTab(tab);
  const {ideasViewKey, onTabChange} = useTabNavigation(id, activeTab);

  const {
    run,
    hypotheses,
    evidence,
    matches,
    reviews,
    report,
    error,
    loaded,
    toast,
    title,
  } = useRunDetailData(id);

  if (!id) return null;

  return (
    <div className={REPORT_PAGE_CLASSES}>
      <ReportTitlebar title={title} />

      <ReportTabNav activeTab={activeTab} onTabChange={onTabChange} />

      <ReportErrorAlert message={error} />

      {!loaded && !error ? (
        <RunDetailSkeleton />
      ) : (
        <RunDetailTabContent
          activeTab={activeTab}
          run={run}
          evidence={evidence}
          report={report}
          hypotheses={hypotheses}
          matches={matches}
          reviews={reviews}
          ideasViewKey={ideasViewKey}
        />
      )}

      {toast && <RunToast message={toast} />}
    </div>
  );
}

// Fetches the run row plus whichever collections `keys` selects (every
// collection when `keys` is omitted), in parallel.
async function fetchRunData(id: string, keys?: ReadonlySet<RunDataKey>) {
  const fetchIfWanted = <T,>(
    key: RunDataKey,
    fetcher: (id: string) => Promise<T>,
  ): Promise<T> | undefined =>
    !keys || keys.has(key) ? fetcher(id) : undefined;
  const [run, hypotheses, evidence, matches, reviews, report] =
    await Promise.all([
      getRun(id),
      fetchIfWanted('hypotheses', getHypotheses),
      fetchIfWanted('evidence', getEvidence),
      fetchIfWanted('matches', getMatches),
      fetchIfWanted('reviews', getReviews),
      fetchIfWanted('report', getReport),
    ]);
  return {run, hypotheses, evidence, matches, reviews, report};
}

// Calls `setState` only when `value` was actually fetched (a selective
// refresh leaves the collections it did not request `undefined`).
function applyIfFetched<T>(value: T | undefined, setState: (value: T) => void) {
  if (value !== undefined) setState(value);
}

// Debounced, key-accumulating scheduler around `refresh`: the SSE stream
// replays the full history on mount and live runs emit rapid bursts, so
// per-event refetches collapse into one trailing call. Data keys accumulate
// in a ref across the debounce window (the underlying debounce keeps only
// the latest call's args), so a burst mixing event types still refetches
// every collection it touched. `cancelPending` drops a pending call without
// touching the accumulated keys (used when a full refresh makes them moot);
// `resetPending` also clears them (used on id change, so a stray key from
// the previous run doesn't leak into the next one's first batch).
function useDebouncedKeyedRefresh(
  refresh: (keys?: ReadonlySet<RunDataKey>) => Promise<void>,
) {
  const pendingRefreshKeys = useRef(new Set<RunDataKey>());
  const debouncedRefresh = useDebouncedCallback(() => {
    const keys = pendingRefreshKeys.current;
    pendingRefreshKeys.current = new Set();
    void refresh(keys);
  }, 600);

  const scheduleRefresh = useCallback(
    (keys: Iterable<RunDataKey>) => {
      for (const key of keys) pendingRefreshKeys.current.add(key);
      debouncedRefresh();
    },
    [debouncedRefresh],
  );

  const cancelPending = useCallback(() => {
    debouncedRefresh.cancel();
  }, [debouncedRefresh]);

  const resetPending = useCallback(() => {
    debouncedRefresh.cancel();
    pendingRefreshKeys.current = new Set();
  }, [debouncedRefresh]);

  return {scheduleRefresh, cancelPending, resetPending};
}

// Fetches and keeps in sync the run row plus its hypotheses/evidence/
// matches/reviews/report collections. `scheduleRefresh` is a debounced
// partial refetch keyed by collection (used by the SSE event stream below),
// and `refreshNow` is an immediate cancel-and-refetch (used on stream
// termination).
function useRunFetch(id: string | undefined) {
  // --- Fetched run data (populated by refresh(), see below) ---
  const [run, setRun] = useState<RunWithSummary | null>(null);
  const [hypotheses, setHypotheses] = useState<Hypothesis[]>([]);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [matches, setMatches] = useState<MatchRow[]>([]);
  const [reviews, setReviews] = useState<Review[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  // With no key set, everything is refetched (initial load, terminal drain).
  // With one, only the run row plus the named collections are, so a mid-run
  // event burst does not fan out to all six endpoints indiscriminately.
  const refresh = useCallback(
    async (keys?: ReadonlySet<RunDataKey>) => {
      if (!id) return;
      try {
        const data = await fetchRunData(id, keys);
        setRun(data.run);
        applyIfFetched(data.hypotheses, setHypotheses);
        applyIfFetched(data.evidence, setEvidence);
        applyIfFetched(data.matches, setMatches);
        applyIfFetched(data.reviews, setReviews);
        applyIfFetched(data.report, setReport);
        setLoaded(true);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        setLoaded(true);
      }
    },
    [id],
  );

  const {scheduleRefresh, cancelPending, resetPending} =
    useDebouncedKeyedRefresh(refresh);

  const refreshNow = useCallback(() => {
    cancelPending();
    void refresh();
  }, [refresh, cancelPending]);

  // Initial load (and reload when the run id changes) stays immediate.
  useEffect(() => {
    resetPending();
    void refresh();
  }, [refresh, resetPending]);

  return {
    run,
    hypotheses,
    evidence,
    matches,
    reviews,
    report,
    error,
    loaded,
    scheduleRefresh,
    refreshNow,
  };
}

// Wires the live SSE event stream for a run (replayed from seq=0 on mount):
// calls `onDataEvents` with the set of collections a coalesced batch of
// events can change, and `onTerminal` once the stream reaches its terminal
// sentinel. Returns `terminal` so callers can derive their own state from it.
function useRunEventStream(
  id: string | undefined,
  onDataEvents: (keys: Iterable<RunDataKey>) => void,
  onTerminal: () => void,
) {
  const {events, terminal} = useRunStream(id ?? null);

  // The stream delivers events in coalesced batches, so scan the whole newly
  // appended slice for data events rather than only the batch tail: a batch
  // that ends in a 'status' event still warrants a refetch if it carried a
  // node event earlier. The processed-count ref resets naturally when the
  // hook clears events on a run change (length drops back toward zero).
  const processedEventCount = useRef(0);
  useEffect(() => {
    if (events.length < processedEventCount.current) {
      processedEventCount.current = 0;
    }
    const fresh = events.slice(processedEventCount.current);
    processedEventCount.current = events.length;
    const data = fresh.filter(event => event.type !== 'status');
    if (data.length === 0) return;
    onDataEvents(dataKeysFromEvents(data));
  }, [events, onDataEvents]);

  // On stream end, refetch immediately so a pending debounce cannot leave the
  // completed state stale.
  useEffect(() => {
    if (!terminal) return;
    onTerminal();
  }, [terminal, onTerminal]);

  return {terminal};
}

// Toast message for a run that just reached a failed/blocked terminal state,
// or null when the run doesn't warrant one.
function runEndToast(run: RunWithSummary): string | null {
  if (run.status !== 'failed' && run.status !== 'blocked') return null;
  return `Run ${run.status}${run.error ? `: ${run.error}` : ''}`;
}

// Derives the toast (shown when a run ends failed/blocked) and the display
// title (curated domain override, else the goal) from the fetched run row,
// and dispatches the title to the shell header.
function useRunDerivedState(run: RunWithSummary | null, terminal: boolean) {
  const [toast, setToast] = useState<string | null>(null);
  useEffect(() => {
    if (!terminal || !run) return;
    const toastMessage = runEndToast(run);
    if (toastMessage) setToast(toastMessage);
  }, [terminal, run]);

  // Full display title. Shared by the shell-header dispatch and the
  // titlebar; each host truncates to its own available width via
  // TruncatedLabel rather than being pre-shortened.
  const title = useMemo(() => {
    if (!run) return 'Goal report';
    return domainTitleOverride(run.research_goal) ?? runGoal(run);
  }, [run]);

  useEffect(() => {
    window.dispatchEvent(
      new CustomEvent('cosci-header-title', {detail: title}),
    );
    return () => {
      window.dispatchEvent(new CustomEvent('cosci-header-title', {detail: ''}));
    };
  }, [title]);

  return {toast, title};
}

// Fetches and keeps in sync all data backing the goal-report surface: the run
// row plus its hypotheses/evidence/matches/reviews/report collections, wired
// to the live SSE event stream so mid-run updates refetch just the
// collections a given event type can change. Also derives the display title
// and dispatches it to the shell header, and raises a toast if the run ends
// failed/blocked.
function useRunDetailData(id: string | undefined) {
  const data = useRunFetch(id);
  const {terminal} = useRunEventStream(
    id,
    data.scheduleRefresh,
    data.refreshNow,
  );
  const {toast, title} = useRunDerivedState(data.run, terminal);

  return {
    run: data.run,
    hypotheses: data.hypotheses,
    evidence: data.evidence,
    matches: data.matches,
    reviews: data.reviews,
    report: data.report,
    error: data.error,
    loaded: data.loaded,
    toast,
    title,
  };
}

// Inline error banner shown above the tab content; renders nothing when
// there is no error.
function ReportErrorAlert({message}: {message: string | null}) {
  if (!message) return null;
  return (
    <div role="alert" className={REPORT_ALERT_CLASSES}>
      {message}
    </div>
  );
}

// Active tab content for a loaded run. Keying <main> by activeTab remounts it
// on tab switch, which also resets any per-tab local UI state (e.g.
// IdeasTab's selection, LearningView's search query).
function RunDetailTabContent({
  activeTab,
  run,
  evidence,
  report,
  hypotheses,
  matches,
  reviews,
  ideasViewKey,
}: {
  activeTab: TabName;
  run: RunWithSummary | null;
  evidence: Evidence[];
  report: Report | null;
  hypotheses: Hypothesis[];
  matches: MatchRow[];
  reviews: Review[];
  ideasViewKey: number;
}) {
  return (
    <main className={REPORT_SCROLL_CLASSES} key={activeTab}>
      {activeTab === 'details' && <GoalDetailsView run={run} />}
      {activeTab === 'learning' && (
        <LearningView goal={runGoal(run)} evidence={evidence} />
      )}
      {activeTab === 'overview' && (
        <ResearchOverviewView
          run={run}
          report={report}
          hypotheses={hypotheses}
          matches={matches}
        />
      )}
      {activeTab === 'ideas' && (
        <section className={ALL_IDEAS_CLASSES}>
          <IdeasTab
            key={ideasViewKey}
            hypotheses={hypotheses}
            reviews={reviews}
            matches={matches}
          />
        </section>
      )}
    </main>
  );
}

// Titlebar: back link plus the run's (possibly domain-overridden) title.
function ReportTitlebar({title}: {title: string}) {
  return (
    <header className={REPORT_TITLEBAR_CLASSES}>
      <div className={REPORT_TITLE_LEFT_CLASSES}>
        <Link to="/" className={REPORT_BACK_CLASSES} aria-label="Back">
          <Icon aria-hidden="true" name="arrow_back" />
        </Link>
        <h1 className={REPORT_TITLE_CLASSES}>
          <TruncatedLabel className={REPORT_TITLE_TEXT_CLASSES} text={title} />
        </h1>
      </div>
    </header>
  );
}

// Tab nav: one button per TABS entry, routed via onTabChange.
function ReportTabNav({
  activeTab,
  onTabChange,
}: {
  activeTab: TabName;
  onTabChange: (tab: TabName) => void;
}) {
  return (
    <nav className={REPORT_TABS_CLASSES} aria-label="Goal report sections">
      {TABS.map(tabName => (
        <button
          key={tabName}
          type="button"
          className={reportTabButtonClass(tabName === activeTab)}
          aria-current={tabName === activeTab ? 'page' : undefined}
          onClick={() => onTabChange(tabName)}
        >
          <Icon
            className={REPORT_TAB_ICON_CLASSES}
            aria-hidden="true"
            name={TAB_ICON_NAMES[tabName]}
          />
          <span className={REPORT_TAB_LABEL_CLASSES}>
            {TAB_LABELS[tabName]}
          </span>
        </button>
      ))}
    </nav>
  );
}

// Picks the selected vs. unselected tab-button class variant.
function reportTabButtonClass(selected: boolean): string {
  return `${REPORT_TAB_BUTTON_BASE_CLASSES} ${
    selected ? REPORT_TAB_SELECTED_CLASSES : 'text-cosci-muted'
  }`;
}

// Requirements/attributes/criteria captured in a run's durable setup config,
// each defaulted to an empty list when the run has no setup yet.
function goalDetailsLists(setup: RunWithSummary['config']['setup']): {
  requirements: string[];
  attributes: string[];
  criteria: string[];
} {
  if (!setup) return {requirements: [], attributes: [], criteria: []};
  return {
    requirements: setup.requirements,
    attributes: setup.attributes,
    criteria: setup.criteria,
  };
}

// "Goal Details" tab: the raw research goal plus the requirements,
// attributes, and criteria captured in the run's setup config.
function GoalDetailsView({run}: {run: RunWithSummary | null}) {
  const goal = runGoal(run) || 'Loading...';
  const {requirements, attributes, criteria} = goalDetailsLists(
    run?.config.setup,
  );

  return (
    <ReportDocument
      title="Research goal details"
      className="cosci-goal-details"
    >
      <h3 className={REPORT_H3_CLASSES}>{domainTitleOverride(goal) ?? goal}</h3>
      <p>
        <strong>Goal:</strong> {goal}
      </p>
      <ReportList title="Requirements" values={requirements} />
      <ReportList title="Attributes" values={attributes} />
      <ReportList title="Criteria" values={criteria} />
    </ReportDocument>
  );
}

// Report-backed overview stats, falling back to the live rows while a run is
// still in flight and has no persisted report yet.
function overviewReportStats(
  report: Report | null,
  hypotheses: Hypothesis[],
  matches: MatchRow[],
): {
  overview: ResearchOverview | undefined;
  leaderboard: ReportPayload['leaderboard'];
  ideaCount: number;
  matchCount: number;
} {
  if (!report) {
    return {
      overview: undefined,
      leaderboard: [],
      ideaCount: hypotheses.length,
      matchCount: matches.length,
    };
  }
  const {payload} = report;
  return {
    overview: payload.research_overview,
    leaderboard: payload.leaderboard,
    ideaCount: payload.hypothesis_count ?? hypotheses.length,
    matchCount: payload.match_count ?? matches.length,
  };
}

// Top ideas by Elo, normalized to one shape from whichever source is
// available: the persisted report leaderboard, else the live hypotheses.
function winningIdeasItems(
  leaderboard: ReportPayload['leaderboard'],
  hypotheses: Hypothesis[],
): {id: string; title: string; elo: number}[] {
  if (leaderboard.length) {
    return leaderboard
      .slice(0, 5)
      .map(item => ({id: item.id, title: item.title, elo: item.elo}));
  }
  return sortByEloDesc(hypotheses)
    .slice(0, 5)
    .map(h => ({id: h.id, title: h.title, elo: h.elo_rating}));
}

// Derives the lead-stat sentence and the top-5 "Winning ideas" list for the
// research-overview tab, memoized off the same report-or-live stats the
// caller already resolved via overviewReportStats.
function useResearchOverviewDerived({
  run,
  leaderboard,
  hypotheses,
  ideaCount,
  matchCount,
}: {
  run: RunWithSummary | null;
  leaderboard: ReportPayload['leaderboard'];
  hypotheses: Hypothesis[];
  ideaCount: number;
  matchCount: number;
}) {
  const leadStat = useMemo(
    () =>
      researchOverviewLeadStat({
        run,
        leaderboard,
        hypotheses,
        ideaCount,
        matchCount,
      }),
    [run, leaderboard, hypotheses, ideaCount, matchCount],
  );

  const winningIdeas = useMemo(
    () => winningIdeasItems(leaderboard, hypotheses),
    [leaderboard, hypotheses],
  );

  return {leadStat, winningIdeas};
}

// "Research Overview" tab: the synthesized report (summary, research
// directions, specific aims), a lead-stat sentence, a top-5 leaderboard, and
// a tournament-match count. Falls back to live hypotheses/matches when no
// persisted report exists yet (run still in progress).
function ResearchOverviewView({
  run,
  report,
  hypotheses,
  matches,
}: {
  run: RunWithSummary | null;
  report: Report | null;
  hypotheses: Hypothesis[];
  matches: MatchRow[];
}) {
  const {overview, leaderboard, ideaCount, matchCount} = overviewReportStats(
    report,
    hypotheses,
    matches,
  );
  const {leadStat, winningIdeas} = useResearchOverviewDerived({
    run,
    leaderboard,
    hypotheses,
    ideaCount,
    matchCount,
  });

  return (
    <ReportDocument title="Research overview">
      {leadStat ? <p className={REPORT_LEAD_STAT_CLASSES}>{leadStat}</p> : null}
      <OverviewSummary overview={overview} />
      <ResearchDirectionsSection overview={overview} />
      <SpecificAimsSection overview={overview} />
      <WinningIdeasSection items={winningIdeas} />
      <TournamentSummarySection matches={matches} />
    </ReportDocument>
  );
}

// Overview summary sentence, or the pre-synthesis placeholder.
function OverviewSummary({overview}: {overview: ResearchOverview | undefined}) {
  const summary = overview?.overview?.summary;
  if (summary) return <p>{summary}</p>;
  return (
    <p>
      The research overview appears after Co-Scientist finishes the final
      synthesis step.
    </p>
  );
}

// "Research directions" section of the research-overview report; renders
// nothing until the report has research directions.
function ResearchDirectionsSection({
  overview,
}: {
  overview: ResearchOverview | undefined;
}) {
  const directions = overview?.overview?.research_directions;
  if (!directions?.length) return null;
  return (
    <section className={REPORT_SECTION_CLASSES}>
      <h3 className={REPORT_H3_CLASSES}>Research directions</h3>
      {directions.map(direction => (
        <div key={direction.title}>
          <h4 className={REPORT_H4_CLASSES}>{direction.title}</h4>
          <p>{direction.importance}</p>
          {direction.suggested_experiments.length ? (
            <ul className={REPORT_LIST_CLASSES}>
              {direction.suggested_experiments.map(experiment => (
                <li key={experiment}>{experiment}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ))}
    </section>
  );
}

// Renders `text` as a paragraph when present, else nothing — used for the
// optional introduction/impact copy around a specific-aims list.
function OptionalParagraph({text}: {text: string | undefined}) {
  if (!text) return null;
  return <p>{text}</p>;
}

// "Specific aims" section of the research-overview report; renders nothing
// until the report has specific aims.
function SpecificAimsSection({
  overview,
}: {
  overview: ResearchOverview | undefined;
}) {
  const specificAims = overview?.nih_specific_aims;
  if (!specificAims?.aims?.length) return null;
  return (
    <section className={REPORT_SECTION_CLASSES}>
      <h3 className={REPORT_H3_CLASSES}>Specific aims</h3>
      <OptionalParagraph text={specificAims.introduction} />
      {specificAims.aims.map(aim => (
        <div key={aim.aim}>
          <h4 className={REPORT_H4_CLASSES}>{aim.aim}</h4>
          <p>{aim.rationale}</p>
          <p>{aim.approach}</p>
        </div>
      ))}
      <OptionalParagraph text={specificAims.impact} />
    </section>
  );
}

// "Winning ideas" section of the research-overview report: top hypotheses by
// Elo, normalized to one shape by the caller; renders nothing when empty.
function WinningIdeasSection({
  items,
}: {
  items: {id: string; title: string; elo: number}[];
}) {
  if (!items.length) return null;
  return (
    <section className={REPORT_SECTION_CLASSES}>
      <h3 className={REPORT_H3_CLASSES}>Winning ideas</h3>
      <ol className={REPORT_LIST_CLASSES}>
        {items.map(item => (
          <li className={REPORT_SECTION_LIST_ITEM_CLASSES} key={item.id}>
            <strong>{item.title}</strong>
            <span className={REPORT_SECTION_LIST_META_CLASSES}>
              Elo rating: {item.elo}
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}

// "Tournament summary" section of the research-overview report.
function TournamentSummarySection({matches}: {matches: MatchRow[]}) {
  return (
    <section className={REPORT_SECTION_CLASSES}>
      <h3 className={REPORT_H3_CLASSES}>Tournament summary</h3>
      <p>
        {matches.length
          ? `${matches.length} tournament matches have been recorded for this run.`
          : 'Tournament matches appear here once ranking begins.'}
      </p>
    </section>
  );
}

// "N thing was/were" pluralization for the lead-stat sentence's clauses.
function pluralPhrase(count: number, singular: string, plural: string): string {
  return count === 1 ? singular : plural;
}

/**
 * Builds the reference's lead stat sentence, e.g. "A total of 133 ideas were
 * explored over 3 hours with the highest Elo rating of 1735 points and a total
 * of 1360 matches were played." Clauses whose data is unknown are omitted, and
 * an empty string is returned when there is nothing meaningful to report yet.
 */
function researchOverviewLeadStat({
  run,
  leaderboard,
  hypotheses,
  ideaCount,
  matchCount,
}: {
  run: RunWithSummary | null;
  leaderboard: {elo: number}[];
  hypotheses: Hypothesis[];
  ideaCount: number;
  matchCount: number;
}): string {
  if (!ideaCount) return '';

  const duration = runDurationPhrase(run);
  const highestElo = Math.max(
    0,
    ...leaderboard.map(item => item.elo),
    ...hypotheses.map(hypothesis => hypothesis.elo_rating),
  );

  const clauses = [
    duration ? ` over ${duration}` : '',
    highestElo > 0
      ? ` with the highest Elo rating of ${highestElo} points`
      : '',
    matchCount > 0
      ? ` and a total of ${matchCount} ${pluralPhrase(matchCount, 'match was', 'matches were')} played`
      : '',
  ];
  const ideaLabel = pluralPhrase(ideaCount, 'idea was', 'ideas were');
  const sentence =
    `A total of ${ideaCount} ${ideaLabel} explored` +
    clauses.filter(Boolean).join('');
  return `${sentence}.`;
}

// completed_at/created_at as a validated pair (both present), or null when
// either timestamp is missing.
function runTimestampPair(
  run: RunWithSummary | null,
): {completedAt: number; createdAt: number} | null {
  if (!run?.completed_at || !run.created_at) return null;
  return {completedAt: run.completed_at, createdAt: run.created_at};
}

/**
 * Formats a run's wall-clock duration (creation to completion) as a rounded
 * human phrase, e.g. "3 hours" or "12 minutes". Returns an empty string when
 * the run has not completed or the timestamps are unusable.
 */
function runDurationPhrase(run: RunWithSummary | null): string {
  const pair = runTimestampPair(run);
  if (!pair) return '';
  const seconds = pair.completedAt - pair.createdAt;
  if (!Number.isFinite(seconds) || seconds <= 0) return '';
  return formatDurationPhrase(seconds);
}

/**
 * Curated display title for known domains, or null to fall back to the
 * goal.
 */
function domainTitleOverride(goal: string): string | null {
  if (isLiverFibrosisGoal(goal)) {
    return 'Epigenetic and stromal reversal strategies for MASH-associated liver fibrosis';
  }
  return null;
}

// Fixed-position status toast, shown when a run ends failed/blocked.
function RunToast({message}: {message: string}) {
  return (
    <div role="status" className={REPORT_TOAST_CLASSES}>
      {message}
    </div>
  );
}

// Resolves the ":tab" route param to a canonical TabName: passes through a
// recognized tab, maps a known alias, and otherwise falls back to 'details'
// (covers both a missing param and an unrecognized value).
function normalizeTab(tab: string | undefined): TabName {
  if (!tab) return 'details';
  if ((TABS as readonly string[]).includes(tab)) return tab as TabName;
  return TAB_ALIASES[tab] ?? 'details';
}

// Loading placeholder shown between mount and the first successful refresh().
function RunDetailSkeleton() {
  return (
    <div className={REPORT_SKELETON_CLASSES} aria-busy="true">
      <div className="wb-skeleton h-8 w-64" />
      <div className="wb-skeleton h-12 w-full" />
      <div className="wb-skeleton h-48 w-full" />
    </div>
  );
}
