import {useParams} from 'react-router-dom';
import {
  type ClaimEvidenceRow,
  type Evidence,
  type Hypothesis,
  type MatchRow,
  type Report,
  type Review,
  type SafetyDecision,
  isActiveStatus,
  runGoal,
  type RunWithSummary,
} from '@/api/runs';
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
    claimEvidence,
    report,
    safety,
    error,
    loaded,
    toast,
    title,
    refreshNow,
    events,
  } = useRunDetailData(id);

  if (!id) return null;

  const active = isActiveStatus(run?.status);
  const pageClasses = active
    ? `${REPORT_PAGE_CLASSES} grid-rows-[3.75rem_minmax(0,1fr)]`
    : REPORT_PAGE_CLASSES;
  return (
    <div className={pageClasses}>
      <ReportTitlebar title={title} />

      {!active && (
        <ReportTabNav activeTab={activeTab} onTabChange={onTabChange} />
      )}

      <ReportErrorAlert message={error} />

      {!loaded && !error ? (
        <RunDetailSkeleton />
      ) : active && run ? (
        <ActiveRunView
          run={run}
          events={events}
          evidenceCount={Math.max(evidence.length, run.summary.evidence)}
          ideaCount={Math.max(hypotheses.length, run.summary.hypotheses)}
        />
      ) : (
        <RunDetailTabContent
          activeTab={activeTab}
          run={run}
          evidence={evidence}
          report={report}
          hypotheses={hypotheses}
          matches={matches}
          reviews={reviews}
          claimEvidence={claimEvidence}
          safety={safety}
          onSafetyChanged={refreshNow}
          ideasViewKey={ideasViewKey}
        />
      )}

      {toast && <RunToast message={toast} />}
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
  claimEvidence,
  safety,
  onSafetyChanged,
  ideasViewKey,
}: {
  activeTab: TabName;
  run: RunWithSummary | null;
  evidence: Evidence[];
  report: Report | null;
  hypotheses: Hypothesis[];
  matches: MatchRow[];
  reviews: Review[];
  claimEvidence: ClaimEvidenceRow[];
  safety: SafetyDecision[];
  onSafetyChanged: () => void;
  ideasViewKey: number;
}) {
  return (
    <main className={REPORT_SCROLL_CLASSES} key={activeTab}>
      {activeTab === 'details' && (
        <RunSpecificationsView
          run={run}
          safety={safety}
          onSafetyChanged={onSafetyChanged}
        />
      )}
      {activeTab === 'learning' && (
        <LearningView goal={runGoal(run)} evidence={evidence} report={report} />
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
            claimEvidence={claimEvidence}
          />
        </section>
      )}
    </main>
  );
}
