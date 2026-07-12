import {useParams} from 'react-router-dom';
import {
  type ClaimEvidenceRow,
  type Evidence,
  type Hypothesis,
  type MatchRow,
  type Report,
  type Review,
  runGoal,
  type RunWithSummary,
} from '@/api/runs';
import {IdeasTab} from '../components/tabs/ideas_tab';
import {useRunDetailData} from './run_detail_data';
import {
  REPORT_H3_CLASSES,
  ReportDocument,
  ReportList,
} from './run_detail_document';
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
import {normalizeTab, type TabName} from '../run_tabs';

const REPORT_PAGE_CLASSES =
  'cosci-report-page grid h-full min-h-0 ' +
  'grid-rows-[3.75rem_5rem_minmax(0,1fr)] bg-cosci-bg text-cosci-fg ' +
  'max-[720px]:min-w-0 max-[720px]:overflow-hidden';

const REPORT_SCROLL_CLASSES =
  'cosci-report-scroll min-h-0 overflow-auto max-[720px]:overflow-x-hidden';

const ALL_IDEAS_CLASSES = 'cosci-all-ideas h-full p-0';

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
          claimEvidence={claimEvidence}
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
  ideasViewKey: number;
}) {
  return (
    <main className={REPORT_SCROLL_CLASSES} key={activeTab}>
      {activeTab === 'specifications' && <RunSpecificationsView run={run} />}
      {activeTab === 'knowledge' && (
        <LearningView goal={runGoal(run)} evidence={evidence} />
      )}
      {activeTab === 'summary' && (
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

// Run Specifications preserves the final interview contract and run mode.
function RunSpecificationsView({run}: {run: RunWithSummary | null}) {
  const goal = runGoal(run) || 'Loading...';
  const {requirements, attributes, criteria} = goalDetailsLists(
    run?.config.setup,
  );

  return (
    <ReportDocument
      title="Run Specifications"
      className="cosci-run-specifications"
    >
      <h3 className={REPORT_H3_CLASSES}>{goal}</h3>
      <p>
        <strong>Research Challenge:</strong> {goal}
      </p>
      <ReportList title="Focus Area" values={attributes} />
      <ReportList title="Preferences" values={requirements} />
      <p>
        <strong>Title:</strong> {run?.title || 'Optional'}
      </p>
      <p>
        <strong>Run type:</strong>{' '}
        {run?.config.tier === 'advanced' ? 'Advanced Run' : 'Standard Run'}
      </p>
      {criteria.length > 0 && (
        <p>
          <strong>Reconstruction provenance:</strong> Legacy criteria are
          retained in the stored run but are not part of the four-field Agent
          interview contract.
        </p>
      )}
    </ReportDocument>
  );
}
