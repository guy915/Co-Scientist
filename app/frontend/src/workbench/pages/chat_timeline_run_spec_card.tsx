import {type RunFocus, type RunTier} from '@/api/runs';
import {Icon} from '@/components/icon';
import {conciseTitle} from '@/lib/text';
import {joinClasses} from '../classes';
import {
  type InferredRunSpec,
  FOCUS_OPTIONS,
  TIER_OPTIONS,
  availableTierOptions,
  isCompletionEmailValid,
  runOptionLabel,
} from '../run_spec';
import {tooltipClassNames} from '../tooltip';
import {AssistantMessage, MessageAttachment} from './chat_timeline_bubble';
import {responseActions} from './chat_timeline_message_actions';
import {planLeadIn} from './chat_timeline_plan_prose';
import {
  type SpecFieldsEditor,
  SpecFieldsSection,
  useSpecFieldsEditor,
} from './chat_timeline_run_spec_editor';
import {CompletionNotification} from './chat_timeline_run_spec_notification';
import {
  OPTION_GROUP_CLASSES,
  OPTION_GROUP_LEGEND_CLASSES,
  OPTION_INPUT_CLASSES,
  OPTION_LABEL_CLASSES,
  OPTION_MARKER_CLASSES,
  OPTION_MARKER_SELECTED_CLASSES,
  SETUP_ACTIONS_CLASSES,
  SETUP_PRIMARY_BUTTON_CLASSES,
  SETUP_SECONDARY_BUTTON_CLASSES,
} from './chat_classes';

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
// confirmed spec). `introReasoning` is the thinking behind that message,
// disclosed inside the turn like any other reply's. `introFallback` marks
// that closing message as
// fallback-authored (no model reachable), so the lead-in carries the same
// quiet notice a fallback bubble does. The remaining handlers wire the
// Focus/Tier options and the cancel/retry/start actions back to the
// session hook.
interface RunSpecCardProps {
  spec: InferredRunSpec;
  /**
   * Timeline item id to tag this card's row with, so the auto-scroll can
   * bring the card's own top edge into view when it arrives (see
   * chat_workspace_scroll.ts). Omitted by the confirmed card, which is a
   * re-render of a card already on screen rather than a new arrival.
   */
  anchorId?: string;
  isStarting: boolean;
  locked?: boolean;
  recoveryAction?: boolean;
  recoveryLookupStatus?: 'checking' | 'error' | 'cancelled';
  onRetryStatusLookup?: () => void;
  intro?: string;
  introReasoning?: string;
  introFallback?: boolean;
  onFocusChange: (focus: RunFocus) => void;
  onTierChange: (tier: RunTier) => void;
  onNotificationChange: (enabled: boolean, email: string) => void;
  onFieldsChange: (patch: Partial<InferredRunSpec>) => void;
  onCancel: () => void;
  onRetry: () => void;
  onStart: () => void;
}

// The Agent's closing interview message with its restatement of the plan
// taken out (chat_timeline_plan_prose.ts -- the document below is where
// those fields live), or a generic lead-in when nothing of it is left: a
// re-shown confirmed spec carrying no message, or a turn that was only the
// summary. `||`, not `??`: an empty closing message must fall back too.
function planIntroText(intro?: string): string {
  return (
    planLeadIn(intro) ||
    'The interview is complete. I derived the research setup below from ' +
      'your answers.'
  );
}

function planInstructions(recoveryAction?: boolean): string {
  if (recoveryAction) {
    return 'This research setup is saved as a draft. Continue research to start the same session.';
  }
  return 'Review the four fields and select a focus and run type. Once ready, click "Start research" to begin.';
}

function startActionLabel(
  isStarting: boolean,
  recoveryAction: boolean,
): string {
  if (isStarting) return recoveryAction ? 'Continuing...' : 'Starting...';
  return recoveryAction ? 'Continue research' : 'Start research';
}

function startActionDisabled({
  isStarting,
  locked,
  recoveryAction,
  canStart,
}: {
  isStarting: boolean;
  locked: boolean;
  recoveryAction: boolean;
  canStart: boolean;
}): boolean {
  return isStarting || (locked && !recoveryAction) || !canStart;
}

function startStatusMessage(recoveryAction: boolean): string {
  return recoveryAction ? 'Continuing research' : 'Starting research';
}

function runSpecResponseActions(props: RunSpecCardProps, responseText: string) {
  return responseActions(
    props.recoveryAction ? null : props.onRetry,
    responseText,
    'co-scientist-research-plan.md',
  );
}

function runPlanEditAction(
  props: RunSpecCardProps,
  editor: SpecFieldsEditor,
): (() => void) | undefined {
  if (props.locked || !props.spec.interviewId || editor.editing) {
    return undefined;
  }
  return editor.startEditing;
}

/**
 * Renders the inferred research-plan turn shown in the timeline once a
 * request has been refined by the Agent: the closing interview message as
 * an ordinary assistant reply, carrying the plan document (four fields, the
 * Focus/Tier groups, and the cancel/start actions) as its inline attachment.
 * Also used, via `locked`, to show a previously-confirmed spec read-only.
 */
export function RunSpecCard(props: RunSpecCardProps) {
  const responseText = formatRunSpecResponse(props.spec);
  const locked = props.locked ?? false;
  // Owned here rather than inside the fields section: the control that
  // opens it is the heading's pencil, which sits outside the plan box.
  const editor = useSpecFieldsEditor(props.spec, props.onFieldsChange);

  return (
    <AssistantMessage
      content={planIntroText(props.intro)}
      fallback={props.introFallback}
      reasoning={props.introReasoning}
      ariaLabel="Inferred run setup"
      anchorId={props.anchorId}
      attachment={
        <MessageAttachment>
          <p className={`reference-review-copy ${'m-0 text-base leading-6'}`}>
            {planInstructions(props.recoveryAction)}
          </p>
          <RecoveryLookupStatus
            status={props.recoveryLookupStatus}
            onRetry={props.onRetryStatusLookup}
          />
          <PlanHeading onEdit={runPlanEditAction(props, editor)} />
          <p className="reference-plan-subheading -mt-[0.35rem] m-0 text-cosci-muted">
            Here's my plan to tackle the topic:
          </p>
          <RunSpecDocument
            spec={props.spec}
            locked={locked}
            isStarting={props.isStarting}
            recoveryAction={props.recoveryAction ?? false}
            editor={editor}
            onFocusChange={props.onFocusChange}
            onTierChange={props.onTierChange}
            onNotificationChange={props.onNotificationChange}
            onCancel={props.onCancel}
            onStart={props.onStart}
          />
        </MessageAttachment>
      }
      actions={runSpecResponseActions(props, responseText)}
    />
  );
}

// The "Research plan" title plus its edit-plan trigger, shown atop
// RunSpecCard's document body. The pencil is the only way into the field
// editor, so it is absent -- not disabled -- whenever there is nothing to
// edit: a locked (already started) card, a spec with no interview behind
// it to save through, and the form's own open state, which carries Save and
// Cancel of its own.
function PlanHeading({onEdit}: {onEdit?: () => void}) {
  return (
    <div className="reference-plan-heading flex items-center gap-[0.45rem]">
      <h2 className="m-0 text-[2rem] leading-[1.2] font-normal tracking-normal text-cosci-fg max-[720px]:text-[clamp(1.5rem,6.8vw,2rem)]">
        Research plan
      </h2>
      {onEdit && (
        <button
          type="button"
          className={tooltipClassNames({
            className:
              'reference-plan-edit size-[2.1rem] grid cursor-pointer place-items-center rounded-full border-0 bg-transparent p-0 text-cosci-muted hover:bg-cosci-hover hover:text-cosci-fg focus-visible:bg-cosci-hover focus-visible:text-cosci-fg',
            placement: 'top',
          })}
          aria-label="Edit plan"
          data-tooltip="Edit plan"
          onClick={onEdit}
        >
          <Icon
            aria-hidden="true"
            className="text-[1.55rem] text-current"
            name="edit"
          />
        </button>
      )}
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
        options={availableTierOptions()}
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
  recoveryAction: boolean;
  editor: SpecFieldsEditor;
  onFocusChange: (focus: RunFocus) => void;
  onTierChange: (tier: RunTier) => void;
  onNotificationChange: (enabled: boolean, email: string) => void;
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
    recoveryAction,
    editor,
    onFocusChange,
    onTierChange,
    onNotificationChange,
    onCancel,
    onStart,
  } = props;
  return (
    <div className="reference-setup-document grid gap-[1.15rem] rounded-2xl bg-cosci-setup-doc-bg p-[1.5rem_1.45rem]">
      <h3 className="m-0 text-[1.45rem] leading-[1.25] font-semibold">
        {spec.title || conciseTitle(spec.goal)}
      </h3>
      <SpecFieldsSection spec={spec} editor={editor} />
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
        recoveryAction={recoveryAction}
        onCancel={onCancel}
        onStart={onStart}
        canStart={isCompletionEmailValid(spec)}
      />
    </div>
  );
}

// A linked DRAFT remains locked for editing, but can be started explicitly
// after a refresh.
function RunSpecActions({
  locked,
  isStarting,
  recoveryAction,
  onCancel,
  onStart,
  canStart,
}: {
  locked: boolean;
  isStarting: boolean;
  recoveryAction: boolean;
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
        aria-busy={isStarting}
        onClick={onStart}
        disabled={startActionDisabled({
          isStarting,
          locked,
          recoveryAction,
          canStart,
        })}
      >
        {startActionLabel(isStarting, recoveryAction)}
      </button>
      {isStarting && (
        <span className="sr-only" role="status" aria-live="polite">
          {startStatusMessage(recoveryAction)}
        </span>
      )}
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
    ...(spec.criteria.length
      ? ['## Criteria', ...spec.criteria.map(value => `* ${value}`), '']
      : []),
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
  disabled?: boolean;
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
        'reference-option-card relative grid min-h-[4.75rem] grid-cols-[1.6rem_minmax(0,1fr)] content-start gap-x-[0.8rem] rounded-[0.65rem] border border-transparent bg-cosci-option-bg px-[0.95rem] py-[0.85rem] text-cosci-fg hover:bg-cosci-option-hover-bg has-[:focus-visible]:border-cosci-option-hover-border has-[:focus-visible]:bg-cosci-option-hover-bg',
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
      <small className="col-start-2 text-[0.92rem] leading-[1.3] text-cosci-muted">
        {option.description}
      </small>
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
      <div className="grid grid-cols-2 gap-[0.85rem] max-[720px]:grid-cols-1">
        {options.map(option => (
          <OptionCard
            key={option.id}
            option={option}
            name={name}
            selected={option.id === value}
            disabled={disabled || Boolean(option.disabled)}
            onChange={onChange}
          />
        ))}
      </div>
    </fieldset>
  );
}

type LookupStatus = 'checking' | 'error' | 'cancelled' | undefined;

function RecoveryLookupStatus({
  status,
  onRetry,
}: {
  status: LookupStatus;
  onRetry?: () => void;
}) {
  if (status === 'checking') {
    return (
      <p role="status" aria-live="polite" className="text-sm text-cosci-muted">
        Checking saved research session status…
      </p>
    );
  }
  if (status === 'error') {
    return (
      <div
        role="alert"
        className="text-sm"
        style={{color: 'var(--md-sys-color-error)'}}
      >
        <p>Could not verify the saved run status.</p>
        <button
          type="button"
          className={SETUP_SECONDARY_BUTTON_CLASSES}
          onClick={onRetry}
        >
          Retry status check
        </button>
      </div>
    );
  }
  if (status === 'cancelled') {
    return (
      <p role="status" className="text-sm text-cosci-muted">
        The linked research session was cancelled.
      </p>
    );
  }
  return null;
}
