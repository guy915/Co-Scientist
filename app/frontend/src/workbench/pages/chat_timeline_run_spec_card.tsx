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
} from './chat_setup_classes';
import {FallbackTurnNotice} from './chat_timeline_bubble';
import {
  MessageActionRow,
  responseActions,
} from './chat_timeline_message_actions';
import {SpecFieldsSection} from './chat_timeline_run_spec_editor';
import {CompletionNotification} from './chat_timeline_run_spec_notification';

// Props for RunSpecCard, named at module level per the destructured prop
// signature otherwise pushing the component past the line cap.
//
// `spec` is the inferred (or confirmed) run specification to display.
// `isStarting` disables the actions and swaps the start button's label while
// a start-run request is in flight. `locked` renders read-only: option
// groups are disabled, Cancel is hidden, and Start is disabled (used for a
// confirmed spec). `intro` is the Agent's closing interview message, shown
// as the card's lead-in so the completed interview reads as a single
// response; it falls back to generic copy when absent (e.g. a re-shown
// confirmed spec). `introFallback` marks that closing message as
// fallback-authored (no model reachable), so the lead-in carries the same
// quiet notice a fallback bubble does. The remaining handlers wire the
// Focus/Tier options and the cancel/edit/retry/start actions back to the
// session hook.
interface RunSpecCardProps {
  spec: InferredRunSpec;
  isStarting: boolean;
  locked?: boolean;
  intro?: string;
  introFallback?: boolean;
  onFocusChange: (focus: RunFocus) => void;
  onTierChange: (tier: RunTier) => void;
  onNotificationChange: (enabled: boolean, email: string) => void;
  onFieldsChange: (patch: Partial<InferredRunSpec>) => void;
  onCancel: () => void;
  onEdit: () => void;
  onRetry: () => void;
  onStart: () => void;
}

// The card's lead-in copy: the Agent's closing interview message (or a
// generic fallback) plus the fixed "review the four fields" paragraph. A
// fallback-authored closing message carries the same quiet notice a fallback
// bubble does, since the lead-in IS that turn.
function RunSpecIntro({intro, fallback}: {intro?: string; fallback?: boolean}) {
  return (
    <>
      {fallback && <FallbackTurnNotice />}
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
    </>
  );
}

/**
 * Renders the inferred research-plan card shown in the timeline once a
 * request has been refined by the Agent: the four interview fields and Tier
 * groups, and the cancel/start actions. Also used, via `locked`, to show a
 * previously-confirmed spec read-only.
 */
export function RunSpecCard(props: RunSpecCardProps) {
  const responseText = formatRunSpecResponse(props.spec);
  const locked = props.locked ?? false;

  return (
    <section className={SETUP_MESSAGE_CLASSES} aria-label="Inferred run setup">
      <RunSpecIntro intro={props.intro} fallback={props.introFallback} />
      <PlanHeading onEdit={props.onEdit} />
      <p className={PLAN_SUBHEADING_CLASSES}>
        Here's my plan to tackle the topic:
      </p>
      <RunSpecDocument
        spec={props.spec}
        locked={locked}
        isStarting={props.isStarting}
        onFocusChange={props.onFocusChange}
        onTierChange={props.onTierChange}
        onNotificationChange={props.onNotificationChange}
        onFieldsChange={props.onFieldsChange}
        onCancel={props.onCancel}
        onStart={props.onStart}
      />
      <MessageActionRow
        actions={responseActions(
          props.onRetry,
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
        aria-label="Revise with the Agent"
        data-tooltip="Revise with the Agent"
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

// The Focus and Run type option-card groups, factored out of
// RunSpecDocument since both share the same value/disabled/onChange shape.
function SpecOptionGroups({
  spec,
  locked,
  onFocusChange,
  onTierChange,
}: {
  spec: InferredRunSpec;
  locked: boolean;
  onFocusChange: (focus: RunFocus) => void;
  onTierChange: (tier: RunTier) => void;
}) {
  return (
    <>
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
    </>
  );
}

// Props for RunSpecDocument, named at module level per the destructured
// prop signature otherwise pushing the component past the line cap.
interface RunSpecDocumentProps {
  spec: InferredRunSpec;
  locked: boolean;
  isStarting: boolean;
  onFocusChange: (focus: RunFocus) => void;
  onTierChange: (tier: RunTier) => void;
  onNotificationChange: (enabled: boolean, email: string) => void;
  onFieldsChange: (patch: Partial<InferredRunSpec>) => void;
  onCancel: () => void;
  onStart: () => void;
}

// Renders the four interview fields and the editable run tier
// option groups, and the cancel/start actions.
function RunSpecDocument(props: RunSpecDocumentProps) {
  const {
    spec,
    locked,
    isStarting,
    onFocusChange,
    onTierChange,
    onNotificationChange,
    onFieldsChange,
    onCancel,
    onStart,
  } = props;
  return (
    <div className={SETUP_DOCUMENT_CLASSES}>
      <h3 className={SETUP_DOCUMENT_TITLE_CLASSES}>
        {spec.title || conciseTitle(spec.goal)}
      </h3>
      <SpecFieldsSection
        spec={spec}
        locked={locked}
        onFieldsChange={onFieldsChange}
      />
      <SpecOptionGroups
        spec={spec}
        locked={locked}
        onFocusChange={onFocusChange}
        onTierChange={onTierChange}
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

// One option in a RunOptionGroup (Focus or Tier).
interface RunOptionGroupOption {
  id: string;
  label: string;
  description: string;
}

// Props for OptionCard, named at module level per the destructured prop
// signature otherwise pushing the component past the line cap.
interface OptionCardProps {
  option: RunOptionGroupOption;
  name: string;
  selected: boolean;
  disabled: boolean;
  onChange: (value: string) => void;
}

// One radio-card in a RunOptionGroup: a native radio input (visually hidden;
// OPTION_INPUT_CLASSES) paired with a styled marker/label/description card
// that reflects the checked state.
function OptionCard(props: OptionCardProps) {
  const {option, name, selected, disabled, onChange} = props;
  return (
    <label
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
        checked={selected}
        disabled={disabled}
        onChange={() => onChange(option.id)}
      />
      <span
        className={joinClasses(
          OPTION_MARKER_CLASSES,
          selected && OPTION_MARKER_SELECTED_CLASSES,
        )}
        aria-hidden="true"
      />
      <strong className={OPTION_LABEL_CLASSES}>{option.label}</strong>
      <small className={OPTION_DESCRIPTION_CLASSES}>{option.description}</small>
    </label>
  );
}

// Renders one radio-card group (Focus or Tier) inside RunSpecCard: one
// OptionCard per option, sharing the group's name/value/disabled/onChange.
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
  options: readonly RunOptionGroupOption[];
  disabled?: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <fieldset className={OPTION_GROUP_CLASSES} aria-label={label}>
      <legend className={OPTION_GROUP_LEGEND_CLASSES}>{label}</legend>
      <div className={OPTION_GRID_CLASSES}>
        {options.map(option => (
          <OptionCard
            key={option.id}
            option={option}
            name={name}
            selected={option.id === value}
            disabled={disabled}
            onChange={onChange}
          />
        ))}
      </div>
    </fieldset>
  );
}
