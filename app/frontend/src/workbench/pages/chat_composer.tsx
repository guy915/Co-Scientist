import {
  type ChangeEvent,
  type Dispatch,
  type FormEvent,
  type KeyboardEvent,
  type RefObject,
  type SetStateAction,
  useLayoutEffect,
  useRef,
} from 'react';
import {joinClasses} from '../classes';
import {Icon} from '@/components/icon';
import {tooltipClassNames} from '../tooltip';
import {
  COMPOSER_ACTIONS_CLASSES,
  COMPOSER_BASE_CLASSES,
  COMPOSER_LABEL_CLASSES,
  COMPOSER_LABEL_ICON_CLASSES,
  COMPOSER_LABEL_TEXT_CLASSES,
  COMPOSER_LABEL_TEXT_HIDDEN_CLASSES,
  COMPOSER_SOURCE_ICON_CLASSES,
  COMPOSER_SUBMIT_BUTTON_CLASSES,
  COMPOSER_TEXTAREA_CLASSES,
  HOME_COMPOSER_CLASSES,
  HOME_COMPOSER_TEXTAREA_CLASSES,
} from './chat_home_classes';
import {
  AttachmentStrip,
  type ComposerAttachment,
  REFERENCE_COMPOSER_ATTACHED_CLASSES,
  useComposerAttachments,
} from './chat_composer_attachments';
import {
  type ConnectorToggleProps,
  SourceControls,
  useConnectorsMenu,
} from './chat_composer_connectors';

// Auto-grow caps (px) before the textarea starts scrolling: the roomier home
// composer grows taller than the compact in-run/setup composer.
const COMPOSER_MAX_HEIGHT = 120;
const COMPOSER_MAX_HEIGHT_LARGE = 146;

/**
 * Props for Composer, named at module level per the destructured prop
 * signature otherwise pushing the component past the line cap.
 *
 * `setupDraftMode` swaps the placeholder copy to "edit session details"
 * wording while a draft/confirmed run spec or started session is showing.
 * `busy` blocks submitting (the send button and Enter) and nothing else: the
 * textarea stays typeable and focused so the next message can be written
 * while the current one is still being answered. `large` selects the roomier
 * home-stage sizing/layout. `autoFocus` takes focus on mount; set on the
 * in-conversation composer, which replaces the home-stage one when the first
 * message is sent, since that swap unmounts the focused textarea and would
 * otherwise drop the caret to the body, forcing a click to carry on typing.
 * `connectors` carries each connector's toggled state and change callback.
 * `onSubmit` handles Enter or the send button.
 */
export interface ComposerProps {
  input: string;
  setInput: (value: string) => void;
  setupDraftMode?: boolean;
  busy: boolean;
  large?: boolean;
  autoFocus?: boolean;
  connectors?: ConnectorToggleProps;
  onSubmit: (e: FormEvent<HTMLFormElement>, files: File[]) => void;
}

// Every connector on, with no owner to write a change back to: the shape a
// Composer rendered without a session behind it (tests, isolated previews)
// shows.
const DEFAULT_CONNECTORS: ConnectorToggleProps = {
  pubmedEnabled: true,
  webSearchEnabled: true,
  paperCorpusEnabled: true,
};

// The optional presentation props, resolved to their defaults in one place so
// Composer itself reads as wiring rather than as a run of fallbacks.
function composerOptions(props: ComposerProps) {
  return {
    large: props.large ?? false,
    setupDraftMode: props.setupDraftMode ?? false,
    autoFocus: props.autoFocus ?? false,
    connectors: props.connectors ?? DEFAULT_CONNECTORS,
  };
}

// Composer's <form onSubmit>: forwards the staged attachments' files to the
// caller's onSubmit, then clears them once the message is actually sent
// (`input.trim()`, since a blank submit is a no-op the caller ignores).
function handleComposerFormSubmit(
  event: FormEvent<HTMLFormElement>,
  input: string,
  state: ComposerState,
  onSubmit: (e: FormEvent<HTMLFormElement>, files: File[]) => void,
): void {
  onSubmit(
    event,
    state.attachments.map(attachment => attachment.file),
  );
  if (input.trim()) state.clearAttachments();
}

/**
 * Renders the message composer: the auto-growing textarea, the file/
 * connector controls beneath it, the submit button, and any staged
 * attachments. Used both as the roomy home-stage composer (`large`) and the
 * compact composer overlaid on the in-conversation timeline.
 */
export function Composer(props: ComposerProps) {
  const {input, setInput, busy, onSubmit} = props;
  const {large, setupDraftMode, autoFocus, connectors} = composerOptions(props);
  const state = useComposerState(input, large);
  const referenceLabel = composerReferenceLabel(setupDraftMode);
  // There is nothing to send while the input is blank, and nothing to send it
  // to while the session is still answering. Both gate submission only; the
  // textarea is never disabled, so typing and focus survive either state.
  const submitDisabled = !input.trim() || busy;

  return (
    <form
      onSubmit={event =>
        handleComposerFormSubmit(event, input, state, onSubmit)
      }
      className={composerFormClassName(
        input,
        large,
        state.attachments.length > 0,
      )}
    >
      <ComposerBody
        input={input}
        setInput={setInput}
        submitDisabled={submitDisabled}
        large={large}
        autoFocus={autoFocus}
        referenceLabel={referenceLabel}
        state={state}
        connectors={connectors}
      />
    </form>
  );
}

// The composer form's className: the base classes plus has-input/large/
// has-attachments modifiers, each applied independently of the others.
function composerFormClassName(
  input: string,
  large: boolean,
  hasAttachments: boolean,
) {
  return joinClasses(
    COMPOSER_BASE_CLASSES,
    input.trim() && 'has-input',
    large && HOME_COMPOSER_CLASSES,
    hasAttachments && REFERENCE_COMPOSER_ATTACHED_CLASSES,
  );
}

// The floating-label copy shown above the textarea: "edit session details"
// wording while a draft/confirmed run spec or started session is showing,
// otherwise the initial call-to-action.
function composerReferenceLabel(setupDraftMode: boolean) {
  return setupDraftMode
    ? 'Type to edit session details'
    : 'Start a new research goal to begin';
}

// Grows the textarea with its content up to a cap, then lets it scroll — the
// reference composer expands as you type before it becomes scrollable. Runs
// on every input change (including programmatic fills from suggestions) so
// the height always tracks the current value; clearing the input snaps it
// back to the CSS min-height floor.
function useAutoGrowTextarea(input: string, large: boolean) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useLayoutEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    const maxHeight = large ? COMPOSER_MAX_HEIGHT_LARGE : COMPOSER_MAX_HEIGHT;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, maxHeight)}px`;
  }, [input, large]);

  return textareaRef;
}

// Owns the composer's non-controlled state: the staged attachments, the
// connectors-menu open flag, and the refs/effects wiring the auto-grow
// textarea, blob-URL cleanup, and outside-click dismissal. `input`/`large`
// are read (not owned) here, only to drive the auto-grow effect.
interface ComposerState {
  fileInputRef: RefObject<HTMLInputElement | null>;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
  sourceControlsRef: RefObject<HTMLDivElement | null>;
  attachments: ComposerAttachment[];
  connectorsOpen: boolean;
  setConnectorsOpen: Dispatch<SetStateAction<boolean>>;
  onFilesChanged: (e: ChangeEvent<HTMLInputElement>) => void;
  removeAttachment: (id: string) => void;
  clearAttachments: () => void;
}

function useComposerState(input: string, large: boolean): ComposerState {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useAutoGrowTextarea(input, large);
  const {attachments, onFilesChanged, removeAttachment, clearAttachments} =
    useComposerAttachments();
  const {connectorsOpen, setConnectorsOpen, sourceControlsRef} =
    useConnectorsMenu();

  return {
    fileInputRef,
    textareaRef,
    sourceControlsRef,
    attachments,
    connectorsOpen,
    setConnectorsOpen,
    onFilesChanged,
    removeAttachment,
    clearAttachments,
  };
}

// The label span above the textarea: the lock icon plus placeholder text,
// hidden once the user has typed anything.
function ComposerLabelText({
  input,
  referenceLabel,
}: {
  input: string;
  referenceLabel: string;
}) {
  return (
    <span
      className={joinClasses(
        COMPOSER_LABEL_TEXT_CLASSES,
        input.trim() && COMPOSER_LABEL_TEXT_HIDDEN_CLASSES,
      )}
    >
      <Icon
        aria-hidden="true"
        className={COMPOSER_LABEL_ICON_CLASSES}
        name="encrypted"
      />
      {referenceLabel}
    </span>
  );
}

// Props for ComposerTextareaField, named at module level per the
// destructured prop signature otherwise pushing the component past the line
// cap.
interface ComposerTextareaFieldProps {
  input: string;
  setInput: (value: string) => void;
  submitDisabled: boolean;
  large: boolean;
  autoFocus: boolean;
  referenceLabel: string;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
}

// The floating-label textarea region: the lock icon + placeholder label
// (hidden once the user has typed anything) above the auto-growing textarea.
function ComposerTextareaField(props: ComposerTextareaFieldProps) {
  const {
    input,
    setInput,
    submitDisabled,
    large,
    autoFocus,
    referenceLabel,
    textareaRef,
  } = props;
  return (
    <label className={COMPOSER_LABEL_CLASSES}>
      <ComposerLabelText input={input} referenceLabel={referenceLabel} />
      <textarea
        ref={textareaRef}
        // One row; the empty height comes from the textarea's min-height and
        // growth is driven by the auto-grow effect. A larger rows value would
        // force the empty box several lines tall.
        rows={1}
        value={input}
        // Restores the focus the home-to-conversation composer swap takes
        // away (see `autoFocus`); it does not take focus from elsewhere on
        // the page, and the home composer leaves it unset.
        autoFocus={autoFocus}
        className={joinClasses(
          COMPOSER_TEXTAREA_CLASSES,
          large && HOME_COMPOSER_TEXTAREA_CLASSES,
        )}
        onChange={e => setInput(e.target.value)}
        onKeyDown={e => handleComposerKeyDown(e, submitDisabled)}
      />
    </label>
  );
}

// Props for ComposerFooter, named at module level per the destructured prop
// signature otherwise pushing the component past the line cap.
interface ComposerFooterProps {
  connectorsOpen: boolean;
  onToggleConnectors: () => void;
  sourceControlsRef: RefObject<HTMLDivElement | null>;
  fileInputRef: RefObject<HTMLInputElement | null>;
  onFilesChanged: (e: ChangeEvent<HTMLInputElement>) => void;
  connectors: ConnectorToggleProps;
  submitDisabled: boolean;
}

// The footer controls row: the file/connector source controls plus the
// submit button.
function ComposerFooter(props: ComposerFooterProps) {
  const {
    connectorsOpen,
    onToggleConnectors,
    sourceControlsRef,
    fileInputRef,
    onFilesChanged,
    connectors,
    submitDisabled,
  } = props;
  return (
    <div className={COMPOSER_ACTIONS_CLASSES}>
      <SourceControls
        connectorsOpen={connectorsOpen}
        onToggleConnectors={onToggleConnectors}
        sourceControlsRef={sourceControlsRef}
        fileInputRef={fileInputRef}
        onFilesChanged={onFilesChanged}
        connectors={connectors}
      />
      <button
        type="submit"
        className={tooltipClassNames({
          className: COMPOSER_SUBMIT_BUTTON_CLASSES,
          placement: 'top',
        })}
        aria-label="Send"
        data-tooltip="Submit"
        disabled={submitDisabled}
      >
        <Icon
          aria-hidden="true"
          className={COMPOSER_SOURCE_ICON_CLASSES}
          name="send"
        />
      </button>
    </div>
  );
}

// Props for ComposerBody, named at module level per the destructured prop
// signature otherwise pushing the component past the line cap.
interface ComposerBodyProps {
  input: string;
  setInput: (value: string) => void;
  submitDisabled: boolean;
  large: boolean;
  autoFocus: boolean;
  referenceLabel: string;
  state: ComposerState;
  connectors: ConnectorToggleProps;
}

// Composer's <form> children: the staged-attachments strip, the textarea
// field, and the footer controls row. Split out so Composer itself only
// wires hooks and props together.
function ComposerBody(props: ComposerBodyProps) {
  const {
    input,
    setInput,
    submitDisabled,
    large,
    autoFocus,
    referenceLabel,
    state,
    connectors,
  } = props;
  return (
    <>
      <AttachmentStrip
        attachments={state.attachments}
        onRemove={state.removeAttachment}
      />
      <ComposerTextareaField
        input={input}
        setInput={setInput}
        submitDisabled={submitDisabled}
        large={large}
        autoFocus={autoFocus}
        referenceLabel={referenceLabel}
        textareaRef={state.textareaRef}
      />
      <ComposerFooter
        connectorsOpen={state.connectorsOpen}
        onToggleConnectors={() => state.setConnectorsOpen(open => !open)}
        sourceControlsRef={state.sourceControlsRef}
        fileInputRef={state.fileInputRef}
        onFilesChanged={state.onFilesChanged}
        connectors={connectors}
        submitDisabled={submitDisabled}
      />
    </>
  );
}

// Enter submits (Shift+Enter still inserts a newline via default behavior).
// When submission is blocked, Enter does nothing at all: requestSubmit() does
// not consult the submit button's disabled state, so without this check Enter
// would still send while the button is greyed out.
function handleComposerKeyDown(
  e: KeyboardEvent<HTMLTextAreaElement>,
  submitDisabled: boolean,
) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    if (!submitDisabled) e.currentTarget.form?.requestSubmit();
  }
}
