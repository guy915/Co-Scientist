import {type ChangeEvent, useEffect, useState} from 'react';
import {useParams} from 'react-router-dom';
import {
  type ClaimEvidenceRow,
  type Evidence,
  type Hypothesis,
  type MatchRow,
  type ProximityEdge,
  type Report,
  type Review,
  type SafetyDecision,
  adjudicateSafety,
  isActiveStatus,
  uploadRunDocument,
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
import {RunAgentDialog} from './run_agent_dialog';

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
  const [agentQuestion, setAgentQuestion] = useState<string | null>(null);
  useEffect(() => {
    const openIdeaAgent = (event: Event) => {
      setAgentQuestion((event as CustomEvent<string>).detail || '');
    };
    window.addEventListener('cosci-open-run-agent', openIdeaAgent);
    return () =>
      window.removeEventListener('cosci-open-run-agent', openIdeaAgent);
  }, []);

  const {
    run,
    hypotheses,
    evidence,
    matches,
    reviews,
    claimEvidence,
    proximity,
    report,
    safety,
    error,
    loaded,
    toast,
    title,
    refreshNow,
  } = useRunDetailData(id);

  if (!id) return null;

  return (
    <div className={REPORT_PAGE_CLASSES}>
      <ReportTitlebar
        title={title}
        runId={id}
        onOpenAgent={() => setAgentQuestion('')}
        shareEnabled={Boolean(run && !run.is_demo)}
      />

      <ReportTabNav activeTab={activeTab} onTabChange={onTabChange} />

      <ReportErrorAlert message={error} />

      {!loaded && !error ? (
        <RunDetailSkeleton />
      ) : (
        <RunDetailTabContent
          activeTab={activeTab}
          runId={id}
          run={run}
          evidence={evidence}
          report={report}
          hypotheses={hypotheses}
          matches={matches}
          reviews={reviews}
          claimEvidence={claimEvidence}
          proximity={proximity}
          safety={safety}
          onSafetyChanged={refreshNow}
          ideasViewKey={ideasViewKey}
        />
      )}

      {toast && <RunToast message={toast} />}
      {agentQuestion !== null && (
        <RunAgentDialog
          runId={id}
          initialQuestion={agentQuestion}
          steering={isActiveStatus(run?.status)}
          onClose={() => setAgentQuestion(null)}
        />
      )}
    </div>
  );
}

// Active tab content for a loaded run. Keying <main> by activeTab remounts it
// on tab switch, which also resets any per-tab local UI state (e.g.
// IdeasTab's selection, LearningView's search query).
function RunDetailTabContent({
  activeTab,
  runId,
  run,
  evidence,
  report,
  hypotheses,
  matches,
  reviews,
  claimEvidence,
  proximity,
  safety,
  onSafetyChanged,
  ideasViewKey,
}: {
  activeTab: TabName;
  runId: string;
  run: RunWithSummary | null;
  evidence: Evidence[];
  report: Report | null;
  hypotheses: Hypothesis[];
  matches: MatchRow[];
  reviews: Review[];
  claimEvidence: ClaimEvidenceRow[];
  proximity: ProximityEdge[];
  safety: SafetyDecision[];
  onSafetyChanged: () => void;
  ideasViewKey: number;
}) {
  return (
    <main className={REPORT_SCROLL_CLASSES} key={activeTab}>
      {activeTab === 'specifications' && (
        <RunSpecificationsView
          run={run}
          safety={safety}
          onSafetyChanged={onSafetyChanged}
        />
      )}
      {activeTab === 'knowledge' && (
        <LearningView goal={runGoal(run)} evidence={evidence} report={report} />
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
            runId={runId}
            hypotheses={hypotheses}
            reviews={reviews}
            matches={matches}
            claimEvidence={claimEvidence}
            proximity={proximity}
            ideaBuckets={report?.payload.idea_buckets}
            onScientistInputChanged={onSafetyChanged}
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
function RunSpecificationsView({
  run,
  safety,
  onSafetyChanged,
}: {
  run: RunWithSummary | null;
  safety: SafetyDecision[];
  onSafetyChanged: () => void;
}) {
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
      <SafetyReviewSection
        runId={run?.id}
        decisions={safety}
        onChanged={onSafetyChanged}
      />
      <PrivateCorpusUpload runId={run?.id} onChanged={onSafetyChanged} />
    </ReportDocument>
  );
}

function PrivateCorpusUpload({
  runId,
  onChanged,
}: {
  runId: string | undefined;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file || !runId) return;
    setBusy(true);
    setStatus(null);
    try {
      const result = await uploadRunDocument(runId, file);
      setStatus(
        `${file.name} indexed (${result.byte_size.toLocaleString()} bytes).`,
      );
      onChanged();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mt-8 border-t border-cosci-border pt-5">
      <h3 className={REPORT_H3_CLASSES}>Private research sources</h3>
      <p>
        Upload a PDF or UTF-8 text, Markdown, CSV, or JSON document. It remains
        scoped to this run and is indexed for subsequent scientific tasks.
      </p>
      <label className="mt-3 inline-flex cursor-pointer rounded-full border border-cosci-border px-4 py-2 text-sm hover:bg-cosci-hover">
        {busy ? 'Indexing…' : 'Upload document'}
        <input
          type="file"
          className="sr-only"
          accept=".pdf,.txt,.md,.csv,.json,application/pdf,text/plain,text/markdown,text/csv,application/json"
          disabled={busy || !runId}
          onChange={event => void upload(event)}
        />
      </label>
      {status && (
        <p role="status" className="mt-2 text-sm">
          {status}
        </p>
      )}
    </section>
  );
}

function SafetyReviewSection({
  runId,
  decisions,
  onChanged,
}: {
  runId: string | undefined;
  decisions: SafetyDecision[];
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState<number | null>(null);
  const reviewable = decisions.filter(
    decision => decision.requires_review && !decision.resolution,
  );
  if (!decisions.length) return null;

  async function resolve(
    decision: SafetyDecision,
    resolution: 'approved' | 'rejected',
  ) {
    if (!runId) return;
    setBusy(decision.id);
    try {
      await adjudicateSafety(runId, decision.id, resolution);
      onChanged();
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="mt-8 border-t border-cosci-border pt-5">
      <h3 className={REPORT_H3_CLASSES}>Safety audit</h3>
      {decisions.map(decision => (
        <div className="mb-5" key={decision.id}>
          <p>
            <strong>{decision.stage}:</strong>{' '}
            {decision.category || decision.decision} — {decision.reason}
          </p>
          <p className="text-sm text-cosci-muted">
            Policy {decision.policy_version || 'legacy'} ·{' '}
            {decision.assessor || 'deterministic'}
          </p>
          {decision.resolution ? (
            <p>Resolution: {decision.resolution}</p>
          ) : null}
          {reviewable.includes(decision) ? (
            <div className="flex gap-2">
              <button
                className="rounded-full border border-cosci-border px-4 py-2"
                disabled={busy === decision.id}
                onClick={() => void resolve(decision, 'approved')}
                type="button"
              >
                Approve for research use
              </button>
              <button
                className="rounded-full border border-cosci-border px-4 py-2"
                disabled={busy === decision.id}
                onClick={() => void resolve(decision, 'rejected')}
                type="button"
              >
                Reject
              </button>
            </div>
          ) : null}
        </div>
      ))}
    </section>
  );
}
