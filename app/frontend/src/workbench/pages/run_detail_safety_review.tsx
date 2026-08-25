import {useState} from 'react';
import {adjudicateSafety, HttpError, type SafetyDecision} from '@/api/runs';
import {REPORT_H3_CLASSES} from './run_detail_document';

type Resolution = 'approved' | 'rejected';

// What each resolution does to the run, shown before it happens: approving
// is consequential and hard to reverse (it releases held content into a
// run that then continues on its own), and rejecting blocks the run
// outright -- neither should fire from a single click.
const CONFIRM_COPY: Record<Resolution, string> = {
  approved: 'This releases the held content and the run resumes on its own.',
  rejected: 'This blocks the run outright.',
};

const BUTTON_CLASSES =
  'rounded-full border border-cosci-border px-4 py-2 disabled:opacity-60';

// One decision's pending confirmation, or none. Scoped to the section (not
// per-item state) because only one decision can be mid-confirmation at a
// time -- opening a second discards whatever the first was asking about.
interface Pending {
  decisionId: number;
  resolution: Resolution;
}

function ResolveButtons({
  busy,
  onRequest,
}: {
  busy: boolean;
  onRequest: (resolution: Resolution) => void;
}) {
  return (
    <div className="flex gap-2">
      <button
        className={BUTTON_CLASSES}
        disabled={busy}
        onClick={() => onRequest('approved')}
        type="button"
      >
        Approve for research use
      </button>
      <button
        className={BUTTON_CLASSES}
        disabled={busy}
        onClick={() => onRequest('rejected')}
        type="button"
      >
        Reject
      </button>
    </div>
  );
}

function ConfirmResolve({
  resolution,
  busy,
  onConfirm,
  onCancel,
}: {
  resolution: Resolution;
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="flex flex-col items-start gap-2">
      <p className="m-0 text-sm">{CONFIRM_COPY[resolution]}</p>
      <div className="flex gap-2">
        <button
          className={BUTTON_CLASSES}
          disabled={busy}
          onClick={onConfirm}
          type="button"
        >
          {resolution === 'approved' ? 'Confirm approve' : 'Confirm reject'}
        </button>
        <button
          className={BUTTON_CLASSES}
          disabled={busy}
          onClick={onCancel}
          type="button"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

// Every decision's resolve UI needs the same five things: whether a call is
// in flight, which resolution (if any) is mid-confirmation, and the three
// actions. Bundled so components pass it as one prop instead of five.
interface ResolveHandlers {
  busy: boolean;
  pending: Resolution | null;
  onRequest: (resolution: Resolution) => void;
  onConfirm: () => void;
  onCancel: () => void;
}

// The approve/reject controls for a decision still awaiting human review:
// the plain buttons, or -- once one is clicked -- the consequence copy and
// a second, explicit confirmation.
function ResolveControls({
  busy,
  pending,
  onRequest,
  onConfirm,
  onCancel,
}: ResolveHandlers) {
  if (pending) {
    return (
      <ConfirmResolve
        resolution={pending}
        busy={busy}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />
    );
  }
  return <ResolveButtons busy={busy} onRequest={onRequest} />;
}

// Display values derived from a safety decision: the human-readable category
// when one was assigned, plus whether it still needs a human resolution. The
// policy version and assessor are decision-internal plumbing and are not
// surfaced here.
function decisionDisplayValues(decision: SafetyDecision) {
  return {
    category: decision.category,
    needsResolution: decision.requires_review && !decision.resolution,
    // A hypothesis the engine's safety screen held out of the pool. It has
    // no hypothesis row of its own, so its decision row is the one place a
    // person can see the idea and adjudicate it.
    heldHypothesis:
      decision.stage === 'hypothesis' && decision.decision === 'hold',
  };
}

// One safety decision: what was flagged and — when it still needs human
// review — the resolve controls (buttons, then a confirmation step).
function SafetyDecisionItem({
  decision,
  resolve,
}: {
  decision: SafetyDecision;
  resolve: ResolveHandlers;
}) {
  const {category, needsResolution, heldHypothesis} =
    decisionDisplayValues(decision);
  return (
    <div className="mb-5">
      {heldHypothesis ? (
        <p>
          <strong>Held for review:</strong> {decision.reason}
        </p>
      ) : (
        <p>
          <strong>{decision.stage}:</strong>{' '}
          {category ? `${category} — ${decision.reason}` : decision.reason}
        </p>
      )}
      {decision.resolution ? <p>Resolution: {decision.resolution}</p> : null}
      {needsResolution ? <ResolveControls {...resolve} /> : null}
    </div>
  );
}

// Whether a decision still needs a human resolution.
function needsReview(decision: SafetyDecision | null): boolean {
  return Boolean(decision?.requires_review && !decision.resolution);
}

// The final screen's own verdict, shown as a plain paragraph instead of a
// generic item -- with resolve controls when it is itself still unresolved.
// A final-stage hold is otherwise unanswerable exactly like an intake hold.
function SafetyAuditSummary({
  decision,
  resolve,
}: {
  decision: SafetyDecision;
  resolve: ResolveHandlers;
}) {
  return (
    <>
      <p className="mb-5">{decision.reason}</p>
      {needsReview(decision) && <ResolveControls {...resolve} />}
    </>
  );
}

// The verdict of the final screen, which is what the audit reads as: one
// per-run row appended after every hypothesis has been gated. Decisions
// arrive oldest-first, so the last matching row is the current one.
function finalDecision(decisions: SafetyDecision[]) {
  const finals = decisions.filter(d => d.stage === 'final');
  return finals.length ? finals[finals.length - 1] : null;
}

// Reviewable decisions other than the summary row: every decision a human
// can act on, minus the final verdict itself (rendered as SafetyAuditSummary
// instead, so it is not shown twice).
function otherReviewableDecisions(
  decisions: SafetyDecision[],
  summary: SafetyDecision | null,
): SafetyDecision[] {
  return decisions.filter(d => d.requires_review && d.id !== summary?.id);
}

// Nothing for a human to see: no final verdict yet, and nothing else needs
// review either.
function hasNothingToReview(
  summary: SafetyDecision | null,
  reviewable: SafetyDecision[],
): boolean {
  return !summary && reviewable.length === 0;
}

// True only when adjudicateSafety lost a race: someone else resolved the
// decision first. Refetching (not a raw error) is the honest response --
// the stale row on screen is what needs fixing, not the click.
function isAlreadyResolvedConflict(error: unknown): boolean {
  return error instanceof HttpError && error.status === 409;
}

// Exported for `run_detail_specifications.tsx`'s upload-error handling, so
// the two nearby error-to-string call sites share one implementation.
export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

interface ResolveState {
  busyId: number | null;
  pending: Pending | null;
  notice: string | null;
}

// Bundles the resolve flow's three pieces of transient state (in flight,
// awaiting confirmation, and the outcome notice) so callers thread one
// object instead of three separate setters through every handler.
function useResolveFlow(runId: string | undefined, onChanged: () => void) {
  const [state, setState] = useState<ResolveState>({
    busyId: null,
    pending: null,
    notice: null,
  });

  function request(decisionId: number, resolution: Resolution) {
    setState({busyId: null, pending: {decisionId, resolution}, notice: null});
  }

  function cancel() {
    setState({busyId: null, pending: null, notice: null});
  }

  async function confirm() {
    const pending = state.pending;
    if (!pending || !runId) return;
    setState({busyId: pending.decisionId, pending: null, notice: null});
    try {
      await adjudicateSafety(runId, pending.decisionId, pending.resolution);
      onChanged();
      setState({busyId: null, pending: null, notice: null});
    } catch (error) {
      if (isAlreadyResolvedConflict(error)) {
        onChanged();
        setState({
          busyId: null,
          pending: null,
          notice: 'Already resolved by someone else. Refreshing…',
        });
      } else {
        setState({busyId: null, pending: null, notice: errorMessage(error)});
      }
    }
  }

  return {state, request, cancel, confirm};
}

export function SafetyReviewSection({
  runId,
  decisions,
  onChanged,
}: {
  runId: string | undefined;
  decisions: SafetyDecision[];
  onChanged: () => void;
}) {
  const {state, request, cancel, confirm} = useResolveFlow(runId, onChanged);
  // The audit is dominated by routine per-hypothesis claim-gate rows that say
  // nothing about the run as a whole, so only the final verdict is shown.
  // Decisions a human must adjudicate are the exception: they carry the
  // resolve controls, and hiding them would strand the review.
  const summary = finalDecision(decisions);
  const reviewable = otherReviewableDecisions(decisions, summary);
  if (hasNothingToReview(summary, reviewable)) return null;

  const resolveFor = (decision: SafetyDecision): ResolveHandlers => ({
    busy: state.busyId === decision.id,
    pending:
      state.pending?.decisionId === decision.id
        ? state.pending.resolution
        : null,
    onRequest: resolution => request(decision.id, resolution),
    onConfirm: () => void confirm(),
    onCancel: cancel,
  });

  return (
    <section className="mt-8 border-t border-cosci-border pt-5">
      <h3 className={REPORT_H3_CLASSES}>Safety audit</h3>
      {state.notice && <p role="status">{state.notice}</p>}
      {summary && (
        <SafetyAuditSummary decision={summary} resolve={resolveFor(summary)} />
      )}
      {reviewable.map(decision => (
        <SafetyDecisionItem
          key={decision.id}
          decision={decision}
          resolve={resolveFor(decision)}
        />
      ))}
    </section>
  );
}
