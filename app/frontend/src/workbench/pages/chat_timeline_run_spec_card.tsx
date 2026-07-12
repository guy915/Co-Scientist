import {type ReactNode} from 'react';
import {type RunFocus, type RunTier} from '@/api/runs';
import {Icon} from '@/components/icon';
import {conciseTitle} from '@/lib/text';
import {FOCUS_OPTIONS, type InferredRunSpec, TIER_OPTIONS} from '../run_spec';
import {tooltipClassNames} from '../tooltip';
import {
  OPTION_CARD_BASE_CLASSES,
  OPTION_DESCRIPTION_CLASSES,
  OPTION_GRID_CLASSES,
  OPTION_GROUP_CLASSES,
  OPTION_GROUP_LEGEND_CLASSES,
  OPTION_INPUT_CLASSES,
  OPTION_LABEL_CLASSES,
  OPTION_MARKER_CLASSES,
  OPTION_MARKER_SELECTED_CLASSES,
  PLAN_EDIT_BUTTON_CLASSES,
  PLAN_EDIT_ICON_CLASSES,
  PLAN_HEADING_CLASSES,
  PLAN_SUBHEADING_CLASSES,
  PLAN_TITLE_CLASSES,
  SETUP_ACTIONS_CLASSES,
  SETUP_DOCUMENT_CLASSES,
  SETUP_DOCUMENT_TITLE_CLASSES,
  SETUP_MESSAGE_CLASSES,
  SETUP_PARAGRAPH_CLASSES,
  SETUP_PRIMARY_BUTTON_CLASSES,
  SETUP_SECONDARY_BUTTON_CLASSES,
  SPEC_DETAIL_CLASSES,
  SPEC_GRID_CLASSES,
  SPEC_LIST_CLASSES,
  SPEC_ROW_CLASSES,
  SPEC_TERM_CLASSES,
} from './chat_setup_classes';
import {
  MessageActionRow,
  responseActions,
} from './chat_timeline_message_actions';

/**
 * Renders the inferred research-plan card shown in the timeline once a
 * request has been parsed into an {@link InferredRunSpec}: the goal/
 * requirements/attributes/criteria breakdown, editable Focus/Tier option
 * groups, and the cancel/start actions. Also used, via `locked`, to show a
 * previously-confirmed spec read-only.
 *
 * @param spec The inferred (or confirmed) run specification to display.
 * @param isStarting Whether a start-run request is in flight, disabling
 *   the actions and swapping the start button's label.
 * @param locked When true, renders read-only: option groups are disabled,
 *   Cancel is hidden, and Start is disabled (used for a confirmed spec).
 * @param onFocusChange Handler for changing the Focus option.
 * @param onTierChange Handler for changing the Tier option.
 * @param onCancel Handler to discard the draft spec.
 * @param onEdit Handler to reopen the originating message for editing.
 * @param onRetry Handler to regenerate/re-stage this spec.
 * @param onStart Handler to start the research run with this spec.
 */
export function RunSpecCard({
  spec,
  isStarting,
  locked = false,
  onFocusChange,
  onTierChange,
  onCancel,
  onEdit,
  onRetry,
  onStart,
}: {
  spec: InferredRunSpec;
  isStarting: boolean;
  locked?: boolean;
  onFocusChange: (focus: RunFocus) => void;
  onTierChange: (tier: RunTier) => void;
  onCancel: () => void;
  onEdit: () => void;
  onRetry: () => void;
  onStart: () => void;
}) {
  const responseText = formatRunSpecResponse(spec);

  return (
    <section className={SETUP_MESSAGE_CLASSES} aria-label="Inferred run setup">
      <p className={SETUP_PARAGRAPH_CLASSES}>
        Okay, I've drafted the requirements to propose a novel, testable
        hypothesis for this research session. Let me know if you have any
        suggestions.
      </p>
      <p className={`reference-review-copy ${SETUP_PARAGRAPH_CLASSES}`}>
        Please review or edit the details below as needed. Once ready, click
        "Start research" to start generating hypotheses.
      </p>
      <PlanHeading onEdit={onEdit} />
      <p className={PLAN_SUBHEADING_CLASSES}>
        Here's my plan to tackle the topic:
      </p>
      <RunSpecDocument
        spec={spec}
        locked={locked}
        isStarting={isStarting}
        onFocusChange={onFocusChange}
        onTierChange={onTierChange}
        onCancel={onCancel}
        onStart={onStart}
      />
      <MessageActionRow
        actions={responseActions(
          onRetry,
          responseText,
          'co-scientist-research-plan.md',
        )}
      />
    </section>
  );
}

// The "Research plan" title plus its edit-plan trigger, shown atop
// RunSpecCard's document body.
function PlanHeading({onEdit}: {onEdit: () => void}) {
  return (
    <div className={PLAN_HEADING_CLASSES}>
      <h2 className={PLAN_TITLE_CLASSES}>Research plan</h2>
      <button
        type="button"
        className={tooltipClassNames({
          className: PLAN_EDIT_BUTTON_CLASSES,
          placement: 'top',
        })}
        aria-label="Edit research plan"
        data-tooltip="Edit research plan"
        onClick={onEdit}
      >
        <Icon
          aria-hidden="true"
          className={PLAN_EDIT_ICON_CLASSES}
          name="edit"
        />
      </button>
    </div>
  );
}

// Renders RunSpecCard's document body: the goal/requirements/attributes/
// criteria breakdown, the editable (or, when `locked`, disabled) Focus/Tier
// option groups, and the cancel/start actions.
function RunSpecDocument({
  spec,
  locked,
  isStarting,
  onFocusChange,
  onTierChange,
  onCancel,
  onStart,
}: {
  spec: InferredRunSpec;
  locked: boolean;
  isStarting: boolean;
  onFocusChange: (focus: RunFocus) => void;
  onTierChange: (tier: RunTier) => void;
  onCancel: () => void;
  onStart: () => void;
}) {
  return (
    <div className={SETUP_DOCUMENT_CLASSES}>
      <h3 className={SETUP_DOCUMENT_TITLE_CLASSES}>
        {conciseTitle(spec.goal)}
      </h3>
      <SpecSummary spec={spec} />
      <RunOptionGroup
        label="Focus"
        name="focus"
        value={spec.focus}
        options={FOCUS_OPTIONS}
        disabled={locked}
        onChange={value => onFocusChange(value as RunFocus)}
      />
      <RunOptionGroup
        label="Tier"
        name="tier"
        value={spec.tier}
        options={TIER_OPTIONS}
        disabled={locked}
        onChange={value => onTierChange(value as RunTier)}
      />
      <RunSpecActions
        locked={locked}
        isStarting={isStarting}
        onCancel={onCancel}
        onStart={onStart}
      />
    </div>
  );
}

// The goal/requirements/attributes/criteria definition list at the top of
// RunSpecDocument.
function SpecSummary({spec}: {spec: InferredRunSpec}) {
  return (
    <dl className={SPEC_GRID_CLASSES}>
      <SpecRow label="Goal">{spec.goal}</SpecRow>
      <SpecList label="Requirements" values={spec.requirements} />
      <SpecList label="Attributes" values={spec.attributes} />
      <SpecList label="Criteria" values={spec.criteria} />
    </dl>
  );
}

// The cancel/start action row under RunSpecDocument: Cancel is hidden when
// `locked` (a confirmed spec can't be discarded), and Start is disabled
// while starting or locked.
function RunSpecActions({
  locked,
  isStarting,
  onCancel,
  onStart,
}: {
  locked: boolean;
  isStarting: boolean;
  onCancel: () => void;
  onStart: () => void;
}) {
  return (
    <div className={SETUP_ACTIONS_CLASSES}>
      {!locked && (
        <button
          type="button"
          className={SETUP_SECONDARY_BUTTON_CLASSES}
          onClick={onCancel}
          disabled={isStarting}
        >
          Cancel
        </button>
      )}
      <button
        type="button"
        className={SETUP_PRIMARY_BUTTON_CLASSES}
        onClick={onStart}
        disabled={isStarting || locked}
      >
        {isStarting ? 'Starting...' : 'Start research'}
      </button>
    </div>
  );
}

// Renders the run spec card's content as a Markdown document, used for the
// card's copy/download actions (see responseActions).
function formatRunSpecResponse(spec: InferredRunSpec): string {
  return [
    `# ${conciseTitle(spec.goal)}`,
    '',
    "I've drafted the requirements to propose a novel, testable hypothesis for this research session.",
    '',
    '## Goal',
    spec.goal,
    '',
    '## Requirements',
    ...spec.requirements.map(value => `* ${value}`),
    '',
    '## Attributes',
    ...spec.attributes.map(value => `* ${value}`),
    '',
    '## Criteria',
    ...spec.criteria.map(value => `* ${value}`),
    '',
    '## Setup Options',
    `* **Focus:** ${runOptionLabel(FOCUS_OPTIONS, spec.focus)}`,
    `* **Tier:** ${runOptionLabel(TIER_OPTIONS, spec.tier)}`,
  ].join('\n');
}

// Looks up an option's display label by id (e.g. FOCUS_OPTIONS/TIER_OPTIONS),
// falling back to the raw value if the id isn't recognized.
function runOptionLabel(
  options: readonly {id: string; label: string}[],
  value: string,
): string {
  return options.find(option => option.id === value)?.label || value;
}

// One term/detail row in the spec definition list (dt/dd pair).
function SpecRow({label, children}: {label: string; children: ReactNode}) {
  return (
    <div className={SPEC_ROW_CLASSES}>
      <dt className={SPEC_TERM_CLASSES}>{label}:</dt>
      <dd className={SPEC_DETAIL_CLASSES}>{children}</dd>
    </div>
  );
}

// A spec row whose value is rendered as a bulleted list (Requirements/
// Attributes/Criteria) rather than plain text (Goal).
function SpecList({label, values}: {label: string; values: string[]}) {
  return (
    <SpecRow label={label}>
      <ul className={SPEC_LIST_CLASSES}>
        {values.map(value => (
          <li key={value}>{value}</li>
        ))}
      </ul>
    </SpecRow>
  );
}

// Renders one radio-card group (Focus or Tier) inside RunSpecCard: a native
// radio input per option (visually hidden; OPTION_INPUT_CLASSES) paired with
// a styled marker/label/description card that reflects the checked state.
function RunOptionGroup({
  label,
  name,
  value,
  options,
  disabled = false,
  onChange,
}: {
  label: string;
  name: string;
  value: string;
  options: readonly {id: string; label: string; description: string}[];
  disabled?: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <fieldset className={OPTION_GROUP_CLASSES} aria-label={label}>
      <legend className={OPTION_GROUP_LEGEND_CLASSES}>{label}</legend>
      <div className={OPTION_GRID_CLASSES}>
        {options.map(option => (
          <label
            key={option.id}
            className={[
              OPTION_CARD_BASE_CLASSES,
              disabled ? 'cursor-default' : 'cursor-pointer',
            ]
              .filter(Boolean)
              .join(' ')}
          >
            <input
              type="radio"
              className={OPTION_INPUT_CLASSES}
              name={name}
              value={option.id}
              checked={option.id === value}
              disabled={disabled}
              onChange={() => onChange(option.id)}
            />
            <span
              className={[
                OPTION_MARKER_CLASSES,
                option.id === value ? OPTION_MARKER_SELECTED_CLASSES : '',
              ]
                .filter(Boolean)
                .join(' ')}
              aria-hidden="true"
            />
            <strong className={OPTION_LABEL_CLASSES}>{option.label}</strong>
            <small className={OPTION_DESCRIPTION_CLASSES}>
              {option.description}
            </small>
          </label>
        ))}
      </div>
    </fieldset>
  );
}
