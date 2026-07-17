import {type ReactNode} from 'react';
import {type RunFocus, type RunTier} from '@/api/runs';
import {Icon} from '@/components/icon';
import {conciseTitle} from '@/lib/text';
import {joinClasses} from '../classes';
import {
  type InferredRunSpec,
  FOCUS_OPTIONS,
  TIER_OPTIONS,
  isCompletionEmailValid,
  runOptionLabel,
} from '../run_spec';
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
 * request has been refined by the Agent: the four interview fields and Tier
 * groups, and the cancel/start actions. Also used, via `locked`, to show a
 * previously-confirmed spec read-only.
 *
 * @param spec The inferred (or confirmed) run specification to display.
 * @param isStarting Whether a start-run request is in flight, disabling
 *   the actions and swapping the start button's label.
 * @param locked When true, renders read-only: option groups are disabled,
 *   Cancel is hidden, and Start is disabled (used for a confirmed spec).
 * @param intro The Agent's closing interview message, shown as the card's
 *   lead-in so the completed interview reads as a single response; falls back
 *   to generic copy when absent (e.g. a re-shown confirmed spec).
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
  intro,
  onFocusChange,
  onTierChange,
  onNotificationChange,
  onCancel,
  onEdit,
  onRetry,
  onStart,
}: {
  spec: InferredRunSpec;
  isStarting: boolean;
  locked?: boolean;
  intro?: string;
  onFocusChange: (focus: RunFocus) => void;
  onTierChange: (tier: RunTier) => void;
  onNotificationChange: (enabled: boolean, email: string) => void;
  onCancel: () => void;
  onEdit: () => void;
  onRetry: () => void;
  onStart: () => void;
}) {
  const responseText = formatRunSpecResponse(spec);

  return (
    <section className={SETUP_MESSAGE_CLASSES} aria-label="Inferred run setup">
      <p className={SETUP_PARAGRAPH_CLASSES}>
        {/* `||`, not `??`: an empty closing message must fall back too. */}
        {intro ||
          'The interview is complete. I derived the research setup below ' +
            'from your answers.'}
      </p>
      <p className={`reference-review-copy ${SETUP_PARAGRAPH_CLASSES}`}>
        Review the four fields and select a focus and run type. Once ready,
        click "Start research" to begin.
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
        onNotificationChange={onNotificationChange}
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

// Renders the four interview fields and the editable run tier
// option groups, and the cancel/start actions.
function RunSpecDocument({
  spec,
  locked,
  isStarting,
  onFocusChange,
  onTierChange,
  onNotificationChange,
  onCancel,
  onStart,
}: {
  spec: InferredRunSpec;
  locked: boolean;
  isStarting: boolean;
  onFocusChange: (focus: RunFocus) => void;
  onTierChange: (tier: RunTier) => void;
  onNotificationChange: (enabled: boolean, email: string) => void;
  onCancel: () => void;
  onStart: () => void;
}) {
  return (
    <div className={SETUP_DOCUMENT_CLASSES}>
      <h3 className={SETUP_DOCUMENT_TITLE_CLASSES}>
        {spec.title || conciseTitle(spec.goal)}
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
        label="Run type"
        name="tier"
        value={spec.tier}
        options={TIER_OPTIONS}
        disabled={locked}
        onChange={value => onTierChange(value as RunTier)}
      />
      <CompletionNotification
        spec={spec}
        disabled={locked}
        onChange={onNotificationChange}
      />
      <RunSpecActions
        locked={locked}
        isStarting={isStarting}
        onCancel={onCancel}
        onStart={onStart}
        canStart={isCompletionEmailValid(spec)}
      />
    </div>
  );
}

function CompletionNotification({
  spec,
  disabled,
  onChange,
}: {
  spec: InferredRunSpec;
  disabled: boolean;
  onChange: (enabled: boolean, email: string) => void;
}) {
  const enabled = Boolean(spec.notifyOnCompletion);
  return (
    <fieldset className={OPTION_GROUP_CLASSES}>
      <legend className={OPTION_GROUP_LEGEND_CLASSES}>Notification</legend>
      <label className="flex items-center gap-3 text-sm">
        <input
          type="checkbox"
          checked={enabled}
          disabled={disabled}
          onChange={event =>
            onChange(event.currentTarget.checked, spec.completionEmail || '')
          }
        />
        Email me when the Goal Report is ready
      </label>
      {enabled ? (
        <input
          type="email"
          required
          disabled={disabled}
          aria-label="Completion notification email"
          className="mt-3 w-full rounded-xl border border-cosci-border bg-transparent p-3"
          value={spec.completionEmail || ''}
          onChange={event => onChange(true, event.currentTarget.value)}
        />
      ) : null}
    </fieldset>
  );
}

// The exact four fields shown by Google's interview progress and setup flow.
function SpecSummary({spec}: {spec: InferredRunSpec}) {
  return (
    <dl className={SPEC_GRID_CLASSES}>
      <SpecRow label="Research Challenge">{spec.goal}</SpecRow>
      <SpecList label="Focus Area" values={spec.attributes} />
      <SpecList label="Preferences" values={spec.requirements} />
      <SpecRow label="Title">{spec.title || 'Optional'}</SpecRow>
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
  canStart,
}: {
  locked: boolean;
  isStarting: boolean;
  onCancel: () => void;
  onStart: () => void;
  canStart: boolean;
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
        disabled={isStarting || locked || !canStart}
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
    `# ${spec.title || conciseTitle(spec.goal)}`,
    '',
    'Agent interview-derived research setup.',
    '',
    '## Research Challenge',
    spec.goal,
    '',
    '## Focus Area',
    ...spec.attributes.map(value => `* ${value}`),
    '',
    '## Preferences',
    ...spec.requirements.map(value => `* ${value}`),
    '',
    '## Title',
    spec.title || 'Optional',
    '',
    '## Setup Options',
    `* **Focus:** ${runOptionLabel(FOCUS_OPTIONS, spec.focus, spec.focus)}`,
    `* **Run type:** ${runOptionLabel(TIER_OPTIONS, spec.tier, spec.tier)}`,
  ].join('\n');
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
            className={joinClasses(
              OPTION_CARD_BASE_CLASSES,
              disabled ? 'cursor-default' : 'cursor-pointer',
            )}
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
              className={joinClasses(
                OPTION_MARKER_CLASSES,
                option.id === value && OPTION_MARKER_SELECTED_CLASSES,
              )}
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
