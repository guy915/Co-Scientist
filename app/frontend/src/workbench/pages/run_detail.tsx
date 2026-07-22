import {useParams} from 'react-router-dom';
import {isActiveStatus, runGoal} from '@/api/runs';
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

/**
 * Renders the Co-Scientist goal report surface from the reference footage.
 */
export function RunDetail() {
  const {id, tab} = useParams<{id: string; tab?: string}>();
  const activeTab = normalizeTab(tab);
  const {ideasViewKey, onTabChange} = useTabNavigation(id, activeTab);
  const data = useRunDetailData(id);

  if (!id) return null;

  const active = isActiveStatus(data.run?.status);
  const pageClasses = active
    ? `${REPORT_PAGE_CLASSES} grid-rows-[3.75rem_minmax(0,1fr)]`
    : REPORT_PAGE_CLASSES;
  return (
    <div className={pageClasses}>
      <ReportTitlebar title={data.title} />

      {!active && (
        <ReportTabNav activeTab={activeTab} onTabChange={onTabChange} />
      )}

      <ReportErrorAlert message={data.error} />

      <RunDetailBody
        active={active}
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
