import type {SupervisorPlanResponse} from '@/api/runs';
import {capitalizeTerm} from '@/lib/text';

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
