import {type ChangeEvent, useState} from 'react';
import {
  type RunCriterion,
  type RunWithSummary,
  type SafetyDecision,
  isTerminalStatus,
  runGoal,
  uploadRunDocument,
  type SupervisorPlanResponse,
} from '@/api/runs';
import {
  FOCUS_OPTIONS,
  TIER_OPTIONS,
  runOptionLabel,
  attributeDisplayString,
} from '../run_spec';
import {
  REPORT_H3_CLASSES,
  ReportDocument,
  ReportList,
} from './run_detail_shell';
import {capitalizeTerm} from '@/lib/text';

const UPLOAD_LABEL_CLASSES =
  'mt-3 inline-flex cursor-pointer rounded-full border border-cosci-border ' +
  'px-4 py-2 text-sm hover:bg-cosci-hover';

export {attributeDisplayString};

// Requirements/attributes/criteria captured in a run's durable setup config,
// each defaulted to an empty list when the run has no setup yet.
function goalDetailsLists(setup: RunWithSummary['config']['setup']): {
  requirements: string[];
  attributes: string[];
  criteria: RunCriterion[];
} {
  if (!setup) return {requirements: [], attributes: [], criteria: []};
  return {
    requirements: setup.requirements,
    attributes: setup.attributes.map(attributeDisplayString),
    criteria: setup.criteria,
  };
}

// The run-option display labels SpecFields needs: title, tier, and focus,
// each defaulted for a run that has not set one.
function specRunLabels(run: RunWithSummary | null): {
  title: string;
  tier: string;
  focus: string;
} {
  return {
    title: run?.title || 'Optional',
    tier: runOptionLabel(TIER_OPTIONS, run?.config.tier, 'Standard'),
    focus: runOptionLabel(FOCUS_OPTIONS, run?.config.focus, 'Balance'),
  };
}

// Every display value SpecFields needs, resolved up front so the component
// itself does no defaulting or lookup of its own.
function specDisplayValues(run: RunWithSummary | null) {
  const {requirements, attributes, criteria} = goalDetailsLists(
    run?.config.setup,
  );
  return {
    goal: runGoal(run) || 'Loading...',
    requirements,
    attributes,
    criteria,
    ...specRunLabels(run),
  };
}

// The interview-contract fields: goal, lists, title, and run options.
function SpecFields({run}: {run: RunWithSummary | null}) {
  const {goal, requirements, attributes, criteria, title, tier, focus} =
    specDisplayValues(run);
  return (
    <>
      <p>
        <strong>Research Challenge:</strong> {goal}
      </p>
      <ReportList title="Focus Area" values={attributes} />
      <ReportList title="Preferences" values={requirements} />
      <p>
        <strong>Title:</strong> {title}
      </p>
      <p>
        <strong>Run type:</strong> {tier}
      </p>
      <p>
        <strong>Focus:</strong> {focus}
      </p>
      {criteria.length > 0 && (
        <p>
          <strong>Reconstruction provenance:</strong> Legacy criteria are
          retained in the stored run but are not part of the four-field Agent
          interview contract.
        </p>
      )}
    </>
  );
}

/** Run Specifications preserves the final interview contract and run mode. */
export function RunSpecificationsView({
  run,
  safety,
  allocationLedger,
  onSafetyChanged,
}: {
  run: RunWithSummary | null;
  safety: SafetyDecision[];
  allocationLedger: AllocationLedgerState;
  onSafetyChanged: () => void;
}) {
  return (
    <ReportDocument
      title="Run Specifications"
      className="cosci-run-specifications"
    >
      <SpecFields run={run} />
      <div className="mt-6">
        <SupervisorAllocationLedger {...allocationLedger} />
      </div>
      <SafetyReviewSection decisions={safety} />
      {run && !isTerminalStatus(run.status) && (
        <PrivateCorpusUpload runId={run.id} onChanged={onSafetyChanged} />
      )}
    </ReportDocument>
  );
}

const UPLOAD_ACCEPT =
  '.pdf,.txt,.md,.csv,.json,application/pdf,text/plain,text/markdown,' +
  'text/csv,application/json';

interface UploadCallbacks {
  setBusy: (busy: boolean) => void;
  setStatus: (status: string | null) => void;
  onChanged: () => void;
}

// Uploads the chosen file into the run's private corpus, reporting progress
// and outcome through the given callbacks.
async function uploadCorpusFile(
  event: ChangeEvent<HTMLInputElement>,
  runId: string | undefined,
  callbacks: UploadCallbacks,
) {
  const file = event.target.files?.[0];
  event.target.value = '';
  if (!file || !runId) return;
  callbacks.setBusy(true);
  callbacks.setStatus(null);
  try {
    const result = await uploadRunDocument(runId, file);
    callbacks.setStatus(
      `${file.name} indexed (${result.byte_size.toLocaleString()} bytes).`,
    );
    callbacks.onChanged();
  } catch (error) {
    callbacks.setStatus(errorMessage(error));
  } finally {
    callbacks.setBusy(false);
  }
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

  const upload = (event: ChangeEvent<HTMLInputElement>) =>
    uploadCorpusFile(event, runId, {setBusy, setStatus, onChanged});

  return (
    <section className="mt-8 border-t border-cosci-border pt-5">
      <h3 className={REPORT_H3_CLASSES}>Private research sources</h3>
      <p>
        Upload a PDF or UTF-8 text, Markdown, CSV, or JSON document. It remains
        scoped to this run and is indexed for subsequent scientific tasks.
      </p>
      <label className={UPLOAD_LABEL_CLASSES}>
        {busy ? 'Indexing…' : 'Upload document'}
        <input
          type="file"
          className="sr-only"
          accept={UPLOAD_ACCEPT}
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

export interface AllocationLedgerState {
  response: SupervisorPlanResponse | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}

/** Native details/summary disclosure for the saved Supervisor decisions. */
export function SupervisorAllocationLedger(props: AllocationLedgerState) {
  const {response} = props;
  return (
    <details
      aria-busy={props.loading}
      aria-label="Supervisor allocation ledger"
      className="rounded-md bg-cosci-hover px-4 py-3"
    >
      <summary tabIndex={0} className="cursor-pointer font-medium">
        Supervisor allocation ledger
        <DecisionCount response={response} />
      </summary>
      <LedgerContents {...props} />
    </details>
  );
}

function DecisionCount({response}: {response: SupervisorPlanResponse | null}) {
  if (!response) return null;
  return (
    <span className="ms-2 text-sm font-normal text-cosci-muted">
      {response.allocations.length} decisions
    </span>
  );
}

function LedgerContents({
  response,
  loading,
  error,
  onRetry,
}: AllocationLedgerState) {
  return (
    <div className="grid gap-3 pt-4">
      <LoadingStatus loading={loading} hasResponse={response !== null} />
      <LedgerError
        error={error}
        hasResponse={response !== null}
        onRetry={onRetry}
      />
      {response && <LedgerEntries response={response} />}
    </div>
  );
}

function LoadingStatus({
  loading,
  hasResponse,
}: {
  loading: boolean;
  hasResponse: boolean;
}) {
  if (!loading) return null;
  return (
    <p role="status" className="text-sm text-cosci-muted">
      {hasResponse
        ? 'Refreshing the allocation ledger…'
        : 'Loading the allocation ledger…'}
    </p>
  );
}

function LedgerError({
  error,
  hasResponse,
  onRetry,
}: {
  error: string | null;
  hasResponse: boolean;
  onRetry: () => void;
}) {
  if (!error) return null;
  return (
    <div role="alert" className="grid justify-items-start gap-2 text-sm">
      <p>
        {hasResponse
          ? 'Could not refresh the allocation ledger. Showing the last saved entries.'
          : 'Could not load the allocation ledger.'}
      </p>
      <button
        type="button"
        className="rounded border border-cosci-border px-3 py-1.5"
        onClick={onRetry}
      >
        Retry loading allocations
      </button>
    </div>
  );
}

function LedgerEntries({response}: {response: SupervisorPlanResponse}) {
  return (
    <>
      <PlanSummary response={response} />
      {response.allocations.length === 0 ? (
        <p className="text-sm text-cosci-muted">
          No scheduling decisions recorded yet.
        </p>
      ) : (
        <ol className="grid gap-3">
          {response.allocations.map(allocation => (
            <li
              key={allocation.id}
              className="rounded border border-cosci-border p-3"
            >
              <h3 className="my-0 text-sm font-medium">
                Decision {allocation.seq + 1} · Iteration {allocation.iteration}
                : {taskLabel(allocation.task_type)}
              </h3>
              <dl className="mt-2 grid gap-2 text-sm">
                <div>
                  <dt className="text-xs text-cosci-muted">
                    Recorded observable reason
                  </dt>
                  <dd className="ms-0">{allocation.reason}</dd>
                </div>
                {allocation.planner_reason?.trim() && (
                  <div>
                    <dt className="text-xs text-cosci-muted">
                      Model-stated rationale
                    </dt>
                    <dd className="ms-0">{allocation.planner_reason}</dd>
                  </div>
                )}
                <div>
                  <dt className="text-xs text-cosci-muted">Status</dt>
                  <dd className="ms-0">{allocation.status}</dd>
                </div>
              </dl>
            </li>
          ))}
        </ol>
      )}
    </>
  );
}

function PlanSummary({response}: {response: SupervisorPlanResponse}) {
  const {decision_provenance: provenance, termination_reason: termination} =
    response.plan ?? {};
  return (
    <>
      <DecisionProvenance value={provenance} />
      <TerminationNotice value={termination} />
    </>
  );
}

function DecisionProvenance({value}: {value?: string | null}) {
  if (!value) return null;
  return (
    <p className="text-sm text-cosci-muted">
      Most recent decision source: {value}
    </p>
  );
}

function TerminationNotice({value}: {value?: string | null}) {
  if (!value) return null;
  return (
    <p className="text-sm text-cosci-muted">Termination reason: {value}</p>
  );
}

function taskLabel(taskType: string): string {
  return capitalizeTerm(taskType.replaceAll('_', ' '));
}

// Upload failures are shown using the server's message when available.
function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

// Show the latest run-wide verdict and decisions flagged for human review.
// Routine claim-gate rows stay out of the audit. Adjudication remains an API
// operation because approval releases held content and resumes the run.
function SafetyReviewSection({decisions}: {decisions: SafetyDecision[]}) {
  const summary = decisions
    .filter(decision => decision.stage === 'final')
    .at(-1);
  const reviewable = decisions.filter(
    decision => decision.requires_review && decision.id !== summary?.id,
  );
  if (!summary && !reviewable.length) return null;

  return (
    <section className="mt-8 border-t border-cosci-border pt-5">
      <h3 className={REPORT_H3_CLASSES}>Safety audit</h3>
      {summary && <p className="mb-5">{summary.reason}</p>}
      {reviewable.map(decision => (
        <div key={decision.id} className="mb-5">
          {decision.stage === 'hypothesis' && decision.decision === 'hold' ? (
            <p>
              <strong>Held for review:</strong> {decision.reason}
            </p>
          ) : (
            <p>
              <strong>{decision.stage}:</strong>{' '}
              {decision.category
                ? `${decision.category} — ${decision.reason}`
                : decision.reason}
            </p>
          )}
          {decision.resolution ? (
            <p>Resolution: {decision.resolution}</p>
          ) : null}
        </div>
      ))}
    </section>
  );
}
