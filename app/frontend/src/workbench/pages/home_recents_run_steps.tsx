import {Fragment} from 'react';
import {Icon, type IconName} from '@/components/icon';

// The four progress steps of a live run, mirroring the reference's session
// loading flow (glyph, label, and the stage boundaries it advances through).
const RUN_STEPS: {icon: IconName; label: string}[] = [
  {icon: 'summarize', label: 'Exploring focus areas'},
  {icon: 'rate_review', label: 'Generating hypotheses'},
  {icon: 'reviews', label: 'Reviewing hypotheses'},
  {icon: 'chess', label: 'Playing tournament'},
];

/**
 * Renders the reference's live "session loading" flow: a "Step X of N" chip
 * over the four run steps, each with its glyph, a green check once done, and an
 * indeterminate spinner on the one currently in progress.
 *
 * @param activeIndex The 1-based index of the step currently running.
 */
export function RunStepFlow({activeIndex}: {activeIndex: number}) {
  return (
    <div className="reference-run-steps">
      <span className="reference-run-step-chip">
        Step {activeIndex} of {RUN_STEPS.length}
      </span>
      <div className="reference-run-step-list">
        {RUN_STEPS.map((step, index) => {
          const stepNumber = index + 1;
          return (
            <Fragment key={step.label}>
              <RunStepItem
                icon={step.icon}
                label={step.label}
                done={stepNumber < activeIndex}
                active={stepNumber === activeIndex}
              />
              {index < RUN_STEPS.length - 1 && (
                <div
                  aria-hidden="true"
                  className="reference-run-step-delimiter"
                />
              )}
            </Fragment>
          );
        })}
      </div>
    </div>
  );
}

// One step's glyph, label, green check once done, and indeterminate spinner
// while it's the one currently in progress.
function RunStepItem({
  icon,
  label,
  done,
  active,
}: {
  icon: IconName;
  label: string;
  done: boolean;
  active: boolean;
}) {
  return (
    <div className="reference-run-step">
      <Icon
        aria-hidden="true"
        className="reference-run-step-icon"
        name={icon}
      />
      <span className="reference-run-step-label">{label}</span>
      {done && (
        <Icon
          aria-hidden="true"
          className="reference-run-step-done"
          name="check"
        />
      )}
      {active && (
        <span aria-hidden="true" className="reference-run-step-spinner" />
      )}
    </div>
  );
}
