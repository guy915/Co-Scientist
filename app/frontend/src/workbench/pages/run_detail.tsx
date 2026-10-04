import {useParams} from 'react-router-dom';
import {
  isCompletedStatus,
  isTerminalNonCompletedStatus,
  runActivity,
  runGoal,
  type RunActivity,
  type RunWithSummary,
  type TerminalNonCompletedStatus,
} from '@/api/runs';
import {useRunHistoryContext} from '@/workbench/hooks/history_context';
import {IdeasTab} from '../components/tabs/ideas_tab';
import {RunOutcomesReport} from '../components/tabs/hypothesis_outcomes';
import {ActiveRunView} from './run_detail_active';
import {useRunDetailData} from './run_detail_data';
import {LearningView} from './run_detail_learning';
import {ResearchOverviewView} from './run_detail_overview';
import {
  AwaitingDecisionNotice,
  ReportErrorAlert,
  reportSectionLabel,
  ReportTabNav,
  ReportTitlebar,
  ReportUngroundedNotice,
  RunDetailSkeleton,
  RunEndState,
  RunToast,
  useTabNavigation,
} from './run_detail_shell';
import {RunSpecificationsView} from './run_detail_specifications';
import {SupervisorAllocationLedger} from './run_detail_specifications';
import {TABS, normalizeTab, type TabName} from '../run_tabs';

// Keep horizontal overflow available to the mobile shell fallback; inner
// report content owns vertical scrolling.
const REPORT_PAGE_CLASSES =
  'cosci-report-page grid h-full min-h-0 bg-cosci-bg text-cosci-fg ' +
  'max-[700px]:min-w-0 max-[700px]:overflow-x-auto ' +
  'max-[700px]:overflow-y-hidden';

const REPORT_SCROLL_CLASSES =
  'cosci-report-scroll min-h-0 overflow-auto max-[700px]:overflow-x-hidden';

const ALL_IDEAS_CLASSES = 'cosci-all-ideas h-full p-0 max-[700px]:h-auto';

type RunDetailData = ReturnType<typeof useRunDetailData>;

// Use history status before fetch completion to avoid flashing finished-report
// chrome for a running run.
function useRunActivity(
  id: string | undefined,
  data: RunDetailData,
): RunActivity {
  const {history} = useRunHistoryContext();
  if (data.loaded) return data.run ? runActivity(data.run.status) : 'inactive';
  return runActivity(history.find(run => run.id === id)?.status);
}

const REPORT_ROWS_WITH_TABS =
  'grid-rows-[3.75rem_5rem_minmax(0,1fr)] ' +
  'max-[700px]:grid-rows-[3.25rem_4.25rem_minmax(0,1fr)] ' +
  '[@media(max-height:500px)]:grid-rows-[3rem_3rem_minmax(0,1fr)]';

const REPORT_ROWS_WITHOUT_TABS =
  'grid-rows-[3.75rem_minmax(0,1fr)] ' +
  'max-[700px]:grid-rows-[3.25rem_minmax(0,1fr)] ' +
  '[@media(max-height:500px)]:grid-rows-[3rem_minmax(0,1fr)]';

function reportPageClasses(showTabs: boolean): string {
  return `${REPORT_PAGE_CLASSES} ${
    showTabs ? REPORT_ROWS_WITH_TABS : REPORT_ROWS_WITHOUT_TABS
  }`;
}

type RunWithBackend = RunWithSummary & {
  llm_backend?: 'offline' | 'real' | null;
};

// Persisted backend is authoritative; legacy mock-provider rows were offline
// and remain illustrative fixtures.
function runUsedOffline(run: RunWithSummary): boolean {
  const backend = (run as RunWithBackend).llm_backend;
  if (backend === undefined || backend === null) {
    return run.provider === 'mock';
  }
  return backend === 'offline';
}

function canRefineOutcomeForRun(run: RunWithSummary | null): boolean {
  return Boolean(
    run &&
    isCompletedStatus(run.status) &&
    run.provider === 'engine' &&
    !run.is_demo,
  );
}

// Flag completed runs without retrieved literature as ungrounded, except
// illustrative offline runs.
function reportIsUngrounded(data: RunDetailData): boolean {
  const run = data.run;
  if (!data.loaded || !run || !isCompletedStatus(run.status)) return false;
  if (data.evidence.length > 0) return false;
  return !runUsedOffline(run);
}

function terminalEndStateOf(run: RunWithSummary | null): {
  status: TerminalNonCompletedStatus;
  error: string | null;
  failureKind: string | null | undefined;
} | null {
  if (run && isTerminalNonCompletedStatus(run.status)) {
    return {
      status: run.status,
      error: run.error,
      failureKind: run.failure_kind,
    };
  }
  return null;
}

function isInitialLoading(data: RunDetailData): boolean {
  return !data.loaded && !data.error;
}

function awaitingDecisionCount(data: RunDetailData): number {
  return data.run?.awaiting_decision_count ?? 0;
}

export function RunDetail() {
  const {id, tab} = useParams<{id: string; tab?: string}>();
  const activeTab = normalizeTab(tab);
  const {ideasViewKey, onTabChange} = useTabNavigation(id, activeTab);
  const data = useRunDetailData(id);
  const activity = useRunActivity(id, data);

  if (!id) return null;

  // Show terminal failure instead of tabs that would present partial output as
  // a finished report.
  const showEndState = terminalEndStateOf(data.run) !== null;
  const showTabs = activity === 'inactive' && !showEndState;
  return (
    <div className={reportPageClasses(showTabs)}>
      <ReportTitlebar title={data.title} activeTab={activeTab} />

      {showTabs && (
        <ReportTabNav
          activeTab={activeTab}
          onTabChange={onTabChange}
          tabs={TABS}
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
        <RunEndState
          status={endState.status}
          error={endState.error}
          failureKind={endState.failureKind}
        />
        <section
          className={
            'mx-auto mt-6 w-[min(100%_-_3rem,58rem)] ' +
            'max-[700px]:w-[min(100%_-_1.2rem,100%)]'
          }
        >
          <SupervisorAllocationLedger
            response={data.supervisorPlan.response}
            loading={data.supervisorPlan.loading}
            error={data.supervisorPlan.error}
            onRetry={data.refreshSupervisorPlan}
          />
        </section>
        <RunOutcomesStatusSection data={data} />
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

function LiveRunSection({data}: {data: RunDetailData}) {
  if (!data.run) return null;
  return (
    <ActiveRunView
      run={data.run}
      events={data.events}
      evidenceCount={Math.max(data.evidence.length, data.run.summary.evidence)}
      ideaCount={Math.max(data.hypotheses.length, data.run.summary.hypotheses)}
      allocationLedger={{
        response: data.supervisorPlan.response,
        loading: data.supervisorPlan.loading,
        error: data.supervisorPlan.error,
        onRetry: data.refreshSupervisorPlan,
      }}
      outcomeStatus={<RunOutcomesStatusSection data={data} />}
    />
  );
}

function RunOutcomesStatusSection({data}: {data: RunDetailData}) {
  return (
    <RunOutcomesReport
      outcomes={data.outcomes}
      hypotheses={data.hypotheses}
      loading={data.outcomesLoading}
      error={data.outcomesError}
      onRefresh={data.refreshOutcomes}
      readOnly={data.run?.is_demo ?? false}
      showRefinementStatus
    />
  );
}

function OverviewSection({data}: {data: RunDetailData}) {
  return (
    <ResearchOverviewView
      run={data.run}
      report={data.report}
      hypotheses={data.hypotheses}
      matches={data.matches}
      outcomes={data.outcomes}
      outcomesLoading={data.outcomesLoading}
      outcomesError={data.outcomesError}
      onRefreshOutcomes={data.refreshOutcomes}
    />
  );
}

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
        runId={data.run?.id ?? ''}
        allowRefinement={canRefineOutcomeForRun(data.run)}
        hypotheses={data.hypotheses}
        reviews={data.reviews}
        matches={data.matches}
        claimEvidence={data.claimEvidence}
        outcomes={data.outcomes}
        outcomesLoading={data.outcomesLoading}
        outcomesError={data.outcomesError}
        isDemo={data.run?.is_demo ?? false}
        onRefreshOutcomes={data.refreshOutcomes}
      />
    </section>
  );
}

const TAB_SECTIONS: Record<
  TabName,
  (ideasViewKey: number, data: RunDetailData) => React.ReactNode
> = {
  details: (_key, data) => (
    <RunSpecificationsView
      run={data.run}
      safety={data.safety}
      allocationLedger={{
        response: data.supervisorPlan.response,
        loading: data.supervisorPlan.loading,
        error: data.supervisorPlan.error,
        onRetry: data.refreshSupervisorPlan,
      }}
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
  ideas: (ideasViewKey, data) => (
    <IdeasSection ideasViewKey={ideasViewKey} data={data} />
  ),
};

function tabSection(
  activeTab: TabName,
  ideasViewKey: number,
  data: RunDetailData,
) {
  return TAB_SECTIONS[activeTab](ideasViewKey, data);
}

// Remount on tab changes to reset local state; keep report-wide notices inside
// the fixed scrolling grid track.
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
