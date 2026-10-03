import type {RunFocus, RunTier} from '@/api/runs';
import {Icon} from '@/components/icon';
import {conciseTitle} from '@/lib/text';
import {
  joinClasses,
  OPTION_GROUP_CLASSES,
  OPTION_GROUP_LEGEND_CLASSES,
  OPTION_INPUT_CLASSES,
  OPTION_LABEL_CLASSES,
  OPTION_MARKER_CLASSES,
  OPTION_MARKER_SELECTED_CLASSES,
  SETUP_ACTIONS_CLASSES,
  SETUP_PRIMARY_BUTTON_CLASSES,
  SETUP_SECONDARY_BUTTON_CLASSES,
} from '../classes';
import {
  type InferredRunSpec,
  FOCUS_OPTIONS,
  TIER_OPTIONS,
  availableTierOptions,
  isCompletionEmailValid,
  runOptionLabel,
  isValidCompletionEmail,
} from '../run_spec';
import {tooltipClassNames} from '../tooltip';
import {AssistantMessage, MessageAttachment} from './chat_timeline_bubble';
import {responseActions} from './chat_timeline_message_actions';
import {
  type SpecFieldsEditor,
  SpecFieldsSection,
  useSpecFieldsEditor,
} from './chat_timeline_run_spec_editor';
import {useSystemStatus} from '../hooks/system_status_context';
import {Link} from 'react-router-dom';
import {TruncatedLabel} from '../components/truncated_label';

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
   * chat_workspace.tsx). Omitted by the confirmed card, which is a
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
// taken out (the document below is where
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

const EMAIL_ROW_CLASSES = 'mt-3 grid gap-1 text-sm';

const EMAIL_LABEL_CLASSES = 'text-cosci-fg';

const EMAIL_INPUT_CLASSES =
  'w-full rounded-xl border border-cosci-border bg-transparent p-3';

/**
 * The completion-email opt-in.
 *
 * There is no separate checkbox: the address field is always present, and
 * notification is simply whichever way a valid address makes it -- typing
 * one on turns it on, clearing or breaking it turns it off. Gated on the
 * server actually having an SMTP transport (`/status`'s
 * `email_notifications_available`): with none configured the durable send
 * task can only raise, exhaust its retries, and fail somewhere the scientist
 * never looks, so an editable field would promise a message that is never
 * coming. Unavailable, the row states that plainly rather than disappearing
 * -- the feature exists, this deployment just cannot send.
 */
export function CompletionNotification({
  spec,
  disabled,
  onChange,
}: {
  spec: InferredRunSpec;
  disabled: boolean;
  onChange: (enabled: boolean, email: string) => void;
}) {
  const {status} = useSystemStatus();
  const available = status?.email_notifications_available ?? false;
  return (
    <fieldset className={OPTION_GROUP_CLASSES}>
      <legend className={OPTION_GROUP_LEGEND_CLASSES}>Notification</legend>
      <NotificationEmail
        spec={spec}
        disabled={disabled}
        available={available}
        onChange={onChange}
      />
      <UnavailableNote available={available} />
    </fieldset>
  );
}

// Says why the field is inert, so an unconfigured server reads as a
// deployment fact rather than a control that ignores keystrokes.
function UnavailableNote({available}: {available: boolean}) {
  if (available) return null;
  return (
    <p className="text-xs text-cosci-muted">
      Email delivery is not configured on this server.
    </p>
  );
}

// The address the Goal Report notice goes to. Always on screen -- entering
// a valid one is the opt-in, an invalid or blank one is a silent opt-out,
// and neither state is announced as an error.
function NotificationEmail({
  spec,
  disabled,
  available,
  onChange,
}: {
  spec: InferredRunSpec;
  disabled: boolean;
  available: boolean;
  onChange: (enabled: boolean, email: string) => void;
}) {
  return (
    <label className={EMAIL_ROW_CLASSES}>
      <span className={EMAIL_LABEL_CLASSES}>
        Email me when the Goal Report is ready
      </span>
      <input
        type="email"
        disabled={disabled || !available}
        placeholder="you@example.com — leave blank for no email"
        className={EMAIL_INPUT_CLASSES}
        value={spec.completionEmail || ''}
        onChange={event => {
          const email = event.currentTarget.value;
          onChange(isValidCompletionEmail(email), email);
        }}
      />
    </label>
  );
}

const STARTED_NEXT_BUTTON_CLASSES =
  'min-h-[2.6rem] cursor-pointer rounded-full border border-cosci-btn-outline-border bg-transparent px-[1.2rem] font-semibold text-cosci-btn-outline-fg hover:bg-cosci-btn-outline-hover-bg focus-visible:bg-cosci-btn-outline-hover-bg';

/** A run that has been started, as shown by the timeline's terminal card. */
export interface StartedSession {
  id: string;
  title: string;
  at: number;
  /**
   * The Agent's reply to the scientist's start request, shown as the card's
   * lead-in so a started run reads as one response rather than a card under
   * a canned notice. Written by the model and streamed in as it arrives
   * (see chat_session_start_run.ts), which is why it grows from empty.
   */
  intro?: string;
  /** The chain of thought behind that reply, disclosed inside the turn like
   * any other reply's. */
  reasoning?: string;
  /**
   * True while the reply is still being written. It is what tells an empty
   * `intro` that is still filling from one that never will, so the standby
   * copy below does not flash in front of the model's own first sentence.
   */
  announcing?: boolean;
}

/**
 * What the card says when no reply was written for it: a run started before
 * this exchange existed and reopened since, a provider that could not be
 * reached, or a turn the scientist stopped.
 *
 * The wording the card carried unconditionally until the Agent started
 * answering for itself. It is the same substance the model is asked for
 * (run under way; open it whenever, first ideas take a few minutes), because
 * the run did start in every one of those cases and the scientist needs the
 * same two facts about it.
 */
export const STARTED_SESSION_STANDBY_COPY =
  'Your session has been started and Co-Scientist has started research!' +
  '\n\n' +
  'You can view and interact with your session at any time, but note that ' +
  'it might take a few minutes for the first ideas to be ready to view.';

// The lead-in text to render: the Agent's own reply, the standby copy once
// it is settled that there will not be one, and nothing at all while the
// reply is still on its way.
function introCopy(session: StartedSession): string {
  const written = session.intro?.trim();
  if (written) return written;
  return session.announcing ? '' : STARTED_SESSION_STANDBY_COPY;
}

/**
 * Renders the terminal timeline turn shown once a research run has actually
 * been started: the Agent's own confirmation as an ordinary assistant reply,
 * carrying the session link card and "what next" actions (open details, or
 * start a new topic) as its inline attachment.
 *
 * @param session The started session (id, title, start timestamp) to display.
 * @param href Route of the run's detail page. A URL rather than an open
 *   handler so both affordances below can be real links, which a middle- or
 *   cmd-click opens in a new browser tab.
 * @param onNewTopic Handler to reset the workspace and start a fresh topic.
 *
 * Carries copy/download but no retry: this card reports a run the server has
 * already started, so there is no response here to regenerate. The control
 * used to re-sort the card to the current time, which from a click looked
 * exactly like nothing happening.
 */
export function StartedSessionCard({
  session,
  href,
  onNewTopic,
}: {
  session: StartedSession;
  href: string;
  onNewTopic: () => void;
}) {
  const intro = introCopy(session);
  const responseText = formatStartedSessionResponse(session, intro);

  return (
    <AssistantMessage
      content={intro}
      reasoning={session.reasoning}
      live={session.announcing}
      ariaLabel="Started research session"
      attachment={
        // Withheld until the reply is written. The turn reads as an answer
        // that hands over the session, so the session block belongs after
        // the answer, not in front of a reply that has not started arriving
        // -- and it grew under the reader's eyes while the text streamed in
        // above it. A run reopened from history has no announcement to wait
        // for (`announcing` is unset) and shows it straight away.
        session.announcing ? undefined : (
          <MessageAttachment>
            <SessionLinkCard session={session} href={href} />
            <SessionNextActions href={href} onNewTopic={onNewTopic} />
          </MessageAttachment>
        )
      }
      actions={responseActions(
        null,
        responseText,
        'co-scientist-session-started.md',
      )}
    />
  );
}

// The clickable card linking to the started session's detail page: title
// (truncated) plus a "Research session" byline and an "Open" affordance.
function SessionLinkCard({
  session,
  href,
}: {
  session: StartedSession;
  href: string;
}) {
  return (
    <Link
      to={href}
      className={`${'reference-started-session-card grid min-h-[5.3rem] cursor-pointer grid-cols-[minmax(0,1fr)_auto] items-center gap-[1.2rem] rounded-2xl border-0 p-[1rem_1rem_1rem_1.35rem] text-left text-white'} no-underline`}
    >
      <span className="block min-w-0">
        <strong className="block min-w-0 text-[1.18rem] leading-[1.25]">
          <TruncatedLabel
            className="block min-w-0 overflow-hidden whitespace-nowrap"
            text={session.title}
          />
        </strong>
        <small className="mt-[0.3rem] block text-[0.9rem] text-white/80">
          Research session
        </small>
      </span>
      <span className="reference-started-open min-w-[5.4rem] rounded-full border border-white/75 px-[1.25rem] py-[0.65rem] text-center font-semibold text-white/90 hover:bg-white/12 focus-visible:bg-white/12">
        Open
      </span>
    </Link>
  );
}

// The "what next" block under a started session: view the session details,
// or start a fresh topic. The first is a navigation, so it is a link wearing
// the pill-button styling rather than a button.
function SessionNextActions({
  href,
  onNewTopic,
}: {
  href: string;
  onNewTopic: () => void;
}) {
  return (
    <div className="reference-started-next flex flex-wrap items-center gap-[0.55rem]">
      <p className="basis-full m-0 mb-[0.1rem] text-[0.95rem] font-semibold text-cosci-muted">
        What would you like to do next?
      </p>
      <Link
        to={href}
        className={`${STARTED_NEXT_BUTTON_CLASSES} inline-flex items-center no-underline`}
      >
        View session details
      </Link>
      <button
        type="button"
        className={STARTED_NEXT_BUTTON_CLASSES}
        onClick={onNewTopic}
      >
        Start a new research goal session on a new topic
      </button>
    </div>
  );
}

// Renders the started-session card's content as a Markdown document, used
// for the card's copy/download actions (see responseActions). Carries the
// reply actually on screen -- the Agent's own, or the standby copy -- rather
// than a second wording of it that would drift from what was read.
function formatStartedSessionResponse(
  session: StartedSession,
  intro: string,
): string {
  return [
    `# ${session.title}`,
    '',
    intro || STARTED_SESSION_STANDBY_COPY,
    '',
    '* **Type:** Research session',
    '* **Action:** Open the session details when you want to inspect progress.',
  ].join('\n');
}

// The headings the summary opens each part with, as the five fields are
// named to the model (`interviews/prompts.py`, "# The five fields") and as
// the plan document labels them. Near-misses are listed because the model
// paraphrases: it is asked for a heading per part, never for these exact
// words.
const PLAN_FIELD_HEADINGS = new Set([
  'research challenge',
  'research goal',
  'research question',
  'challenge',
  'goal',
  'focus area',
  'focus areas',
  'focus',
  'preference',
  'preferences',
  'lab constraint',
  'lab constraints',
  'laboratory constraints',
  'constraints',
  'title',
]);

const HEADING_PATTERN = /^ {0,3}#{1,6} +(.*?) *#* *$/;

// A line that is part of a list, table, quote or heading rather than of a
// plain paragraph.
const STRUCTURED_LINE = /^ {0,3}([#>|]|[-*+] |\d+[.)] )/;

// A horizontal rule, which the model uses to separate the summary's parts.
const RULE_LINE = /^ {0,3}(-{3,}|\*{3,}|_{3,}) *$/;

// A heading's text, stripped to what it names: emphasis markers, numbering,
// a trailing parenthetical and trailing punctuation all vary between turns
// and none of them change which field the heading is about. The
// parenthetical is not hypothetical -- a live turn headed its title section
// "Title (proposed)", which is the section anyway.
function headingLabel(line: string): string | null {
  const match = HEADING_PATTERN.exec(line);
  if (!match) return null;
  return match[1]
    .replace(/[*_`\\]/g, '')
    .replace(/^\d+[.)]\s*/, '')
    .replace(/\s*\([^)]*\)\s*$/, '')
    .replace(/[:.\-–—]+\s*$/, '')
    .trim()
    .toLowerCase();
}

// Every line except those under a heading that names a plan field. A field
// heading opens a dropped run; the next heading of any kind closes it.
function withoutFieldSections(source: string): string {
  const kept: string[] = [];
  let dropping = false;
  for (const line of source.split('\n')) {
    const label = headingLabel(line);
    if (label !== null) dropping = PLAN_FIELD_HEADINGS.has(label);
    if (!dropping) kept.push(line);
  }
  return kept.join('\n');
}

function isBlankOrRule(line: string): boolean {
  return !line.trim() || RULE_LINE.test(line);
}

// Drops the blank lines and separator rules left dangling where a section
// was cut out, and collapses the gaps between what survived.
function tidy(text: string): string {
  const lines = text.split('\n');
  while (lines.length && isBlankOrRule(lines[0])) lines.shift();
  while (lines.length && isBlankOrRule(lines[lines.length - 1])) lines.pop();
  return lines.join('\n').replace(/\n{3,}/g, '\n\n');
}

/**
 * The turn's closing sentence, when it ends on one.
 *
 * The completing turn is asked to end by saying the run can be started or
 * the scope refined further, and it writes that after the summary -- which
 * puts it inside the last section cut above even though it is not part of
 * the plan. Recognised by position and shape: the last paragraph of the
 * turn, made only of prose lines.
 */
function signOff(source: string): string {
  const blocks = source.split(/\n[ \t]*\n/);
  const last = (blocks[blocks.length - 1] ?? '').trim();
  if (!last) return '';
  const structured = last.split('\n').some(line => STRUCTURED_LINE.test(line));
  return structured ? '' : last;
}

/**
 * The completing interview turn as the plan turn shows it: everything the
 * model wrote except its restatement of the plan.
 *
 * @param intro The Agent's closing message, as persisted.
 * @returns The prose to render above the plan document; empty when the turn
 *   was nothing but the summary and carried no sign-off, which leaves the
 *   card on its own generic lead-in.
 */
export function planLeadIn(intro?: string): string {
  const source = (intro ?? '').trim();
  if (!source) return '';
  return withSignOff(tidy(withoutFieldSections(source)), signOff(source));
}

// Puts the sign-off back under whatever survived, unless it is already
// there (a turn that carried no summary keeps its own last paragraph).
function withSignOff(kept: string, closing: string): string {
  if (!closing || kept.endsWith(closing)) return kept;
  return kept ? `${kept}\n\n${closing}` : closing;
}
