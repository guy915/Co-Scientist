/**
 * The detail pane's "Review critiques" section body, including each review
 * row's structured findings (R14-15/R14-22) alongside its free-text
 * critique.
 *
 * Split out of `ideas_detail_pane.tsx` to keep that module within the
 * repo's 500-line ceiling.
 */
import type {Review} from '@/api/runs';
import {
  hasReviewDetail,
  NO_REVIEW_CRITIQUES_TEXT,
  parseReviewDetail,
  type ReviewDetail,
  reviewCritiqueText,
  reviewerLabel,
} from './ideas_detail_data';

// The full/recurrent review's display-only Go/No-Go framing (R14-15).
// Zero overlap with that row's critique text (correctness/quality/
// literature-grounding/justification/assumptions) -- a pure complement, so
// it renders unconditionally alongside the critique below it.
function VerdictLines({detail}: {detail: ReviewDetail}) {
  if (!detail.goNoGo && !detail.timeToVerdict) return null;
  return (
    <>
      {detail.goNoGo && (
        <p>
          <strong>Verdict: </strong>
          {detail.goNoGo}
        </p>
      )}
      {detail.timeToVerdict && (
        <p>
          <strong>Time to verdict: </strong>
          {detail.timeToVerdict}
        </p>
      )}
    </>
  );
}

// The simulation review's numbered failure points and decisive step
// (R14-22), matching report_markdown_hypothesis's bolded/numbered shape.
// The reviewer heading above this block already reads "Simulation review"
// (reviewerLabel), mirroring the markdown's own `#### Simulation review` --
// no second heading is needed here.
//
// This is the one reviewer type whose critique text already carries the
// same failure-point/decisive-step lines, flattened into that row's prose
// (report_markdown_hypothesis's critique formatter joins them with the
// row's "Simulated model"/step/robustness lines). The critique stays
// unedited below rather than having those lines stripped out of it: doing
// so would couple this component to that prose's exact label format, which
// is not a contract either side promises to hold still, and the critique is
// the only surface carrying the simulated model, per-step commentary, and
// robustness assessment this structured detail does not. The bolded list
// leads so a scanning reader sees the named failure points first, the way
// the report does.
function SimulationFindings({detail}: {detail: ReviewDetail}) {
  if (!detail.failurePoints.length && !detail.decisiveStep) return null;
  return (
    <>
      {detail.failurePoints.length > 0 && (
        <ol className="list-decimal pl-5">
          {detail.failurePoints.map((point, i) => (
            <li key={i}>
              <strong>Failure point:</strong> {point}
            </li>
          ))}
        </ol>
      )}
      {detail.decisiveStep && (
        <p>
          <strong>Decisive step: </strong>
          {detail.decisiveStep}
        </p>
      )}
    </>
  );
}

// One review row's structured findings, when its detail_json parsed to
// anything -- nothing for a row that predates the column, carries no
// structured content, or is malformed past recovery.
function ReviewFindings({review}: {review: Review}) {
  const detail = parseReviewDetail(review);
  if (!hasReviewDetail(detail)) return null;
  return (
    <div className="mb-1">
      <VerdictLines detail={detail} />
      <SimulationFindings detail={detail} />
    </div>
  );
}

// "Review critiques" section body: every review row recorded for the idea,
// each under its reviewer's own heading, so the initial peer review, the
// deep verification, and the full/simulation/recurrent results stay
// visibly distinct findings (audit E1/D13) instead of one collapsed block.
// A row carrying structured detail_json (R14-15/R14-22) surfaces it above
// the free-text critique -- see ReviewFindings/SimulationFindings for why
// both render rather than one replacing the other. Props-only (no hooks).
export function ReviewCritiquesContent({reviews}: {reviews: Review[]}) {
  if (!reviews.length) {
    return <p>{NO_REVIEW_CRITIQUES_TEXT}</p>;
  }
  return (
    <>
      {reviews.map(item => (
        <div key={item.id} className="mb-3 last:mb-0">
          <h3>{reviewerLabel(item.reviewer_agent)}</h3>
          <ReviewFindings review={item} />
          <p>{reviewCritiqueText(item)}</p>
        </div>
      ))}
    </>
  );
}
