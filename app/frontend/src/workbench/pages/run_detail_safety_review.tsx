import {type SafetyDecision} from '@/api/runs';
import {REPORT_H3_CLASSES} from './run_detail_shell';

// Display values derived from a safety decision: the human-readable category
// when one was assigned. The policy version and assessor are
// decision-internal plumbing and are not surfaced here.
function decisionDisplayValues(decision: SafetyDecision) {
  return {
    category: decision.category,
    // A hypothesis the engine's safety screen held out of the pool. It has
    // no hypothesis row of its own, so its decision row is the one place a
    // person can see the idea at all.
    heldHypothesis:
      decision.stage === 'hypothesis' && decision.decision === 'hold',
  };
}

// One safety decision: what was flagged, and its resolution once one has
// been recorded.
function SafetyDecisionItem({decision}: {decision: SafetyDecision}) {
  const {category, heldHypothesis} = decisionDisplayValues(decision);
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
    </div>
  );
}

// The final screen's own verdict, shown as a plain paragraph instead of a
// generic item -- it reports on the run as a whole rather than on one piece
// of content.
function SafetyAuditSummary({decision}: {decision: SafetyDecision}) {
  return <p className="mb-5">{decision.reason}</p>;
}

// The verdict of the final screen, which is what the audit reads as: one
// per-run row appended after every hypothesis has been gated. Decisions
// arrive oldest-first, so the last matching row is the current one.
function finalDecision(decisions: SafetyDecision[]) {
  const finals = decisions.filter(d => d.stage === 'final');
  return finals.length ? finals[finals.length - 1] : null;
}

// Flagged decisions other than the summary row: every decision marked for
// human review, minus the final verdict itself (rendered as
// SafetyAuditSummary instead, so it is not shown twice).
function otherReviewableDecisions(
  decisions: SafetyDecision[],
  summary: SafetyDecision | null,
): SafetyDecision[] {
  return decisions.filter(d => d.requires_review && d.id !== summary?.id);
}

// Nothing for a human to see: no final verdict yet, and nothing else was
// flagged either.
function hasNothingToReview(
  summary: SafetyDecision | null,
  reviewable: SafetyDecision[],
): boolean {
  return !summary && reviewable.length === 0;
}

// Exported for `run_detail_specifications.tsx`'s upload-error handling.
export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/**
 * The run's safety audit: the final screen's verdict plus any decision
 * flagged for human review.
 *
 * Read-only by design. Adjudicating a held decision is a consequential,
 * hard-to-reverse act -- approving releases withheld content into a run
 * that then continues on its own -- so it is not offered as a button beside
 * the report. `POST /api/runs/{id}/safety/{decision_id}/adjudicate` remains
 * the way to resolve one, and a resolution recorded there shows up here.
 *
 * @param decisions Every safety decision recorded for the run.
 */
export function SafetyReviewSection({
  decisions,
}: {
  decisions: SafetyDecision[];
}) {
  // The audit is dominated by routine per-hypothesis claim-gate rows that say
  // nothing about the run as a whole, so only the final verdict is shown.
  // Decisions flagged for human review are the exception: they name content
  // the run withheld, which the reader would otherwise never see.
  const summary = finalDecision(decisions);
  const reviewable = otherReviewableDecisions(decisions, summary);
  if (hasNothingToReview(summary, reviewable)) return null;

  return (
    <section className="mt-8 border-t border-cosci-border pt-5">
      <h3 className={REPORT_H3_CLASSES}>Safety audit</h3>
      {summary && <SafetyAuditSummary decision={summary} />}
      {reviewable.map(decision => (
        <SafetyDecisionItem key={decision.id} decision={decision} />
      ))}
    </section>
  );
}
