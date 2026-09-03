import {useParams} from 'react-router-dom';
import {
  isActiveStatus,
  type RunStatus,
  type RunWithSummary,
  runGoal,
} from '@/api/runs';
import {useRunHistoryContext} from '@/workbench/hooks/run_history_context';
import {IdeasTab} from '../components/tabs/ideas_tab';
import {ActiveRunView} from './run_detail_active';
import {useRunDetailData} from './run_detail_data';
import {LearningView} from './run_detail_learning';
import {ResearchOverviewView} from './run_detail_overview';
import {RankingDocumentView} from './run_detail_ranking';
import {
  AwaitingDecisionNotice,
  isTerminalNonCompletedStatus,
  ReportErrorAlert,
  reportSectionLabel,
  ReportTabNav,
  ReportTitlebar,
  ReportUngroundedNotice,
  RunDetailSkeleton,
  RunEndState,
  RunToast,
  type TerminalNonCompletedStatus,
  useTabNavigation,
} from './run_detail_shell';
import {RunSpecificationsView} from './run_detail_specifications';
import {TABS, normalizeTab, type TabName} from '../run_tabs';

// max-[700px]:overflow-x-auto (not overflow-hidden): the ancestor .ucs-page
// --report was given a horizontal-scroll fallback for content that shrinks
// below what it contains (see shell_surface.css); an unconditional
// overflow-hidden here would keep clipping locally before that ancestor ever
// saw the overflow. overflow-y stays hidden -- vertical scrolling is owned
// by the inner .cosci-report-scroll region below.
const REPORT_PAGE_CLASSES =
  'cosci-report-page grid h-full min-h-0 ' +
  'grid-rows-[3.75rem_5rem_minmax(0,1fr)] bg-cosci-bg text-cosci-fg ' +
  'max-[700px]:min-w-0 max-[700px]:overflow-x-auto ' +
  'max-[700px]:overflow-y-hidden';

const REPORT_SCROLL_CLASSES =
  'cosci-report-scroll min-h-0 overflow-auto max-[700px]:overflow-x-hidden';

const ALL_IDEAS_CLASSES = 'cosci-all-ideas h-full p-0 max-[700px]:h-auto';

type RunDetailData = ReturnType<typeof useRunDetailData>;

// Whether the run is executing. 'unknown' is a real third state: until the
// run row (or the shell's history) says otherwise, neither the results chrome
// nor the live view is the right guess.
type RunActivity = 'active' | 'inactive' | 'unknown';

function activityOf(status: RunStatus | undefined): RunActivity {
  if (!status) return 'unknown';
  return isActiveStatus(status) ? 'active' : 'inactive';
}

// The run's activity, known as early as possible. The fetched row wins once
// it lands (a row that failed to load counts as settled, so an errored page
// still offers its tabs). Before that the shell's run-history list already
// carries the status of every listed run, so a running run opened from the
// sidebar picks the live view on its very first paint instead of flashing the
// previous run's report chrome for the length of a fetch.
function useRunActivity(
  id: string | undefined,
  data: RunDetailData,
): RunActivity {
  const {history} = useRunHistoryContext();
  if (data.loaded) return data.run ? activityOf(data.run.status) : 'inactive';
  return activityOf(history.find(run => run.id === id)?.status);
}

// The page grid: only a settled, non-active run gets the tab-nav row, since
// ActiveRunView replaces the tabbed body entirely and an unknown activity has
// no business painting chrome it may be about to drop. A run that ended
// without completing gets no tab row either -- it renders its end state.
function reportPageClasses(showTabs: boolean): string {
  return showTabs
    ? REPORT_PAGE_CLASSES
    : `${REPORT_PAGE_CLASSES} grid-rows-[3.75rem_minmax(0,1fr)]`;
}

// The run payload carries the persisted LLM backend the run executed on
// ("offline" deterministic router vs "real" provider). The shared Run type
// predates the field, so it is read through a local extension.
type RunWithBackend = RunWithSummary & {
  llm_backend?: 'offline' | 'real' | null;
};

// Mirrors the backend's store.run_used_offline: the persisted llm_backend
// column is authoritative; rows created before the column existed fall back
// to the provider (the mock provider was always offline-backed). Offline
// runs are illustrative fixtures -- the same convention get_hypotheses uses
// to exempt them from "Unverified" badging.
function runUsedOffline(run: RunWithSummary): boolean {
  const backend = (run as RunWithBackend).llm_backend;
  if (backend === undefined || backend === null) {
    return run.provider === 'mock';
  }
  return backend === 'offline';
}

// A completed run whose literature retrieval returned nothing still reads
// categorically; flag it as ungrounded unless it was offline-backed.
function reportIsUngrounded(data: RunDetailData): boolean {
  const run = data.run;
  if (!data.loaded || !run || run.status !== 'completed') return false;
  if (data.evidence.length > 0) return false;
  return !runUsedOffline(run);
}

// The end-state facts of a run that terminated without completing, or null
// for every other run (including an unloaded one).
function terminalEndStateOf(run: RunWithSummary | null): {
  status: TerminalNonCompletedStatus;
  error: string | null;
} | null {
  if (run && isTerminalNonCompletedStatus(run.status)) {
    return {status: run.status, error: run.error};
  }
  return null;
}

// Before the first fetch settles (and nothing has failed), the page is
// still guessing at what it should paint.
function isInitialLoading(data: RunDetailData): boolean {
  return !data.loaded && !data.error;
}

// Zero for an unloaded run, matching the field's own "not paused, or
// nothing left to review" meaning of zero (see `Run.awaiting_decision_count`).
function awaitingDecisionCount(data: RunDetailData): number {
  return data.run?.awaiting_decision_count ?? 0;
}

// R14-11: the ranking tab shows only for a run whose report actually
// carries a Top Ranking Hypotheses document -- null/absent on a run
// persisted before the split, which keeps its four original tabs exactly
// as before. `TABS` stays the full five-entry route table (so a direct
// link to /runs/:id/ranking still resolves) -- only the nav strip's own
// list is filtered.
function visibleTabs(data: RunDetailData): readonly TabName[] {
  if (data.report?.markdown_text_ranking) return TABS;
  return TABS.filter(tab => tab !== 'ranking');
}

/**
 * Renders the Co-Scientist goal report surface from the reference footage.
 */
export function RunDetail() {
  const {id, tab} = useParams<{id: string; tab?: string}>();
  const activeTab = normalizeTab(tab);
  const {ideasViewKey, onTabChange} = useTabNavigation(id, activeTab);
  const data = useRunDetailData(id);
  const activity = useRunActivity(id, data);

  if (!id) return null;

  // A run that ended without completing shows its end state (status plus
  // recorded error) instead of report tabs: content for it either does not
  // exist or would present a partial run as finished.
  const showEndState = terminalEndStateOf(data.run) !== null;
  const showTabs = activity === 'inactive' && !showEndState;
  return (
    <div className={reportPageClasses(showTabs)}>
      <ReportTitlebar title={data.title} activeTab={activeTab} />

      {showTabs && (
        <ReportTabNav
          activeTab={activeTab}
          onTabChange={onTabChange}
          tabs={visibleTabs(data)}
        />
      )}

      <ReportErrorAlert message={data.error} />

      <RunDetailBody
        active={activity === 'active'}
        activeTab={activeTab}
        ideasViewKey={ideasViewKey}
        data={data}
      />

      {data.toast && <RunToast message={data.toast} />}
    </div>
  );
}

interface RunDetailBodyProps {
  active: boolean;
  activeTab: TabName;
  ideasViewKey: number;
  data: RunDetailData;
}

// Chooses the loading skeleton, the terminal end state, the live-run view,
// or the tab content.
function RunDetailBody({
  active,
  activeTab,
  ideasViewKey,
  data,
}: RunDetailBodyProps) {
  if (isInitialLoading(data)) return <RunDetailSkeleton />;
  const endState = terminalEndStateOf(data.run);
  if (endState) {
    return (
      <main className={REPORT_SCROLL_CLASSES}>
        <RunEndState status={endState.status} error={endState.error} />
      </main>
    );
  }
  if (active && data.run) return <LiveRunSection data={data} />;
  return (
    <RunDetailTabContent
      activeTab={activeTab}
      ideasViewKey={ideasViewKey}
      data={data}
    />
  );
}

// The live view of an in-flight run.
function LiveRunSection({data}: {data: RunDetailData}) {
  if (!data.run) return null;
  return (
    <ActiveRunView
      run={data.run}
      events={data.events}
      evidenceCount={Math.max(data.evidence.length, data.run.summary.evidence)}
      ideaCount={Math.max(data.hypotheses.length, data.run.summary.hypotheses)}
    />
  );
}

// The Overview tab body.
function OverviewSection({data}: {data: RunDetailData}) {
  return (
    <ResearchOverviewView
      run={data.run}
      report={data.report}
      hypotheses={data.hypotheses}
      matches={data.matches}
    />
  );
}

// The Ideas tab body, remount-keyed so switching back resets its selection.
function IdeasSection({
  ideasViewKey,
  data,
}: {
  ideasViewKey: number;
  data: RunDetailData;
}) {
  return (
    <section className={ALL_IDEAS_CLASSES}>
      <IdeasTab
        key={ideasViewKey}
        hypotheses={data.hypotheses}
        reviews={data.reviews}
        matches={data.matches}
        claimEvidence={data.claimEvidence}
      />
    </section>
  );
}

// One tab's content, given the loaded run data. A table rather than an
// if-chain so adding a tab is one entry and a missing one is a compile
// error -- the same reason TAB_META is keyed by TabName.
const TAB_SECTIONS: Record<
  TabName,
  (ideasViewKey: number, data: RunDetailData) => React.ReactNode
> = {
  details: (_key, data) => (
    <RunSpecificationsView
      run={data.run}
      safety={data.safety}
      onSafetyChanged={data.refreshNow}
    />
  ),
  learning: (_key, data) => (
    <LearningView
      goal={runGoal(data.run)}
      evidence={data.evidence}
      report={data.report}
    />
  ),
  overview: (_key, data) => <OverviewSection data={data} />,
  ranking: (_key, data) => <RankingDocumentView report={data.report} />,
  ideas: (ideasViewKey, data) => (
    <IdeasSection ideasViewKey={ideasViewKey} data={data} />
  ),
};

// The active tab's content section.
function tabSection(
  activeTab: TabName,
  ideasViewKey: number,
  data: RunDetailData,
) {
  return TAB_SECTIONS[activeTab](ideasViewKey, data);
}

// Active tab content for a loaded run. Keying <main> by activeTab remounts it
// on tab switch, which also resets any per-tab local UI state (e.g.
// IdeasTab's selection, LearningView's search query). The awaiting-decision
// and ungrounded notices ride above every tab's content because both apply
// to the whole report -- rendered inside this scrolling region rather than
// as a sibling of it, since `.cosci-report-page`'s grid-rows template is
// sized for a fixed set of siblings; an extra one lands in an unsized
// implicit track and its content overflows that track's box (see the
// AwaitingDecisionNotice/heading overlap this replaced).
function RunDetailTabContent({
  activeTab,
  ideasViewKey,
  data,
}: Omit<RunDetailBodyProps, 'active'>) {
  return (
    <main
      className={REPORT_SCROLL_CLASSES}
      key={activeTab}
      aria-label={reportSectionLabel(activeTab)}
    >
      <AwaitingDecisionNotice count={awaitingDecisionCount(data)} />
      {reportIsUngrounded(data) && <ReportUngroundedNotice />}
      {tabSection(activeTab, ideasViewKey, data)}
    </main>
  );
}
