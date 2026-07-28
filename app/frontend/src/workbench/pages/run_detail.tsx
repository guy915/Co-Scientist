import {useParams} from 'react-router-dom';
import {isActiveStatus, type RunStatus, runGoal} from '@/api/runs';
import {useChatHistoryContext} from '@/workbench/hooks/chat_history_context';
import {useRunHistoryContext} from '@/workbench/hooks/run_history_context';
import {IdeasTab} from '../components/tabs/ideas_tab';
import {ActiveRunView} from './run_detail_active';
import {useRunDetailData} from './run_detail_data';
import {LearningView} from './run_detail_learning';
import {ResearchOverviewView} from './run_detail_overview';
import {
  ReportErrorAlert,
  ReportTabNav,
  ReportTitlebar,
  RunDetailSkeleton,
  RunToast,
  useTabNavigation,
} from './run_detail_shell';
import {RunSpecificationsView} from './run_detail_specifications';
import {normalizeTab, type TabName} from '../run_tabs';

const REPORT_PAGE_CLASSES =
  'cosci-report-page grid h-full min-h-0 ' +
  'grid-rows-[3.75rem_5rem_minmax(0,1fr)] bg-cosci-bg text-cosci-fg ' +
  'max-[720px]:min-w-0 max-[720px]:overflow-hidden';

const REPORT_SCROLL_CLASSES =
  'cosci-report-scroll min-h-0 overflow-auto max-[720px]:overflow-x-hidden';

const ALL_IDEAS_CLASSES = 'cosci-all-ideas h-full p-0 max-[720px]:h-auto';

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
// no business painting chrome it may be about to drop.
function reportPageClasses(showTabs: boolean): string {
  return showTabs
    ? REPORT_PAGE_CLASSES
    : `${REPORT_PAGE_CLASSES} grid-rows-[3.75rem_minmax(0,1fr)]`;
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
  // The conversation this run came from, so the titlebar's back arrow
  // returns to it rather than to an empty workspace.
  const {chats} = useChatHistoryContext();

  if (!id) return null;

  const showTabs = activity === 'inactive';
  const chatId = chats.find(chat => chat.run_id === id)?.id;
  return (
    <div className={reportPageClasses(showTabs)}>
      <ReportTitlebar title={data.title} chatId={chatId} />

      {showTabs && (
        <ReportTabNav activeTab={activeTab} onTabChange={onTabChange} />
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

// Chooses the loading skeleton, the live-run view, or the tab content.
function RunDetailBody({
  active,
  activeTab,
  ideasViewKey,
  data,
}: RunDetailBodyProps) {
  if (!data.loaded && !data.error) return <RunDetailSkeleton />;
  if (active && data.run) {
    return (
      <ActiveRunView
        run={data.run}
        events={data.events}
        evidenceCount={Math.max(
          data.evidence.length,
          data.run.summary.evidence,
        )}
        ideaCount={Math.max(
          data.hypotheses.length,
          data.run.summary.hypotheses,
        )}
      />
    );
  }
  return (
    <RunDetailTabContent
      activeTab={activeTab}
      ideasViewKey={ideasViewKey}
      data={data}
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

// Active tab content for a loaded run. Keying <main> by activeTab remounts it
// on tab switch, which also resets any per-tab local UI state (e.g.
// IdeasTab's selection, LearningView's search query).
function RunDetailTabContent({
  activeTab,
  ideasViewKey,
  data,
}: Omit<RunDetailBodyProps, 'active'>) {
  return (
    <main className={REPORT_SCROLL_CLASSES} key={activeTab}>
      {activeTab === 'details' && (
        <RunSpecificationsView
          run={data.run}
          safety={data.safety}
          onSafetyChanged={data.refreshNow}
        />
      )}
      {activeTab === 'learning' && (
        <LearningView
          goal={runGoal(data.run)}
          evidence={data.evidence}
          report={data.report}
        />
      )}
      {activeTab === 'overview' && (
        <ResearchOverviewView
          run={data.run}
          report={data.report}
          hypotheses={data.hypotheses}
          matches={data.matches}
        />
      )}
      {activeTab === 'ideas' && (
        <IdeasSection ideasViewKey={ideasViewKey} data={data} />
      )}
    </main>
  );
}
