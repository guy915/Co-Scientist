import {
  type ChangeEvent,
  type FormEvent,
  type KeyboardEvent,
  type RefObject,
  useEffect,
  useLayoutEffect,
  useRef,
} from 'react';
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
  REFERENCE_COMPOSER_ATTACHED_CLASSES,
  useComposerAttachments,
} from './chat_composer_attachments';
import {SourceControls, useConnectorsMenu} from './chat_composer_connectors';

// Auto-grow caps (px) before the textarea starts scrolling: the roomier home
// composer grows taller than the compact in-run/setup composer.
const COMPOSER_MAX_HEIGHT = 120;
const COMPOSER_MAX_HEIGHT_LARGE = 146;

/**
 * Renders the message composer: the auto-growing textarea, the file/
 * connector controls beneath it, the submit button, and any staged
 * attachments. Used both as the roomy home-stage composer (`large`) and the
 * compact composer overlaid on the in-conversation timeline.
 *
 * @param input Controlled textarea value, owned by the parent session state.
 * @param setInput Updates the controlled textarea value.
 * @param setupDraftMode Swaps the placeholder copy to "edit session details"
 *   wording while a draft/confirmed run spec or started session is showing.
 * @param disabled Disables input and the source-control buttons (e.g. while
 *   starting a run).
 * @param large Selects the roomier home-stage sizing/layout.
 * @param pubmedEnabled Whether the PubMed connector is currently toggled on.
 * @param onPubmedEnabledChange Callback fired when the PubMed toggle changes.
 * @param onSubmit Form submit handler (Enter or the send button).
 */
export function Composer({
  input,
  setInput,
  setupDraftMode = false,
  disabled,
  large = false,
  pubmedEnabled = true,
  onPubmedEnabledChange,
  onSubmit,
}: {
  input: string;
  setInput: (value: string) => void;
  setupDraftMode?: boolean;
  disabled: boolean;
  large?: boolean;
  pubmedEnabled?: boolean;
  onPubmedEnabledChange?: (value: boolean) => void;
  onSubmit: (e: FormEvent<HTMLFormElement>, files: File[]) => void;
}) {
  const {
    fileInputRef,
    textareaRef,
    sourceControlsRef,
    attachments,
    connectorsOpen,
    setConnectorsOpen,
    onFilesChanged,
    removeAttachment,
    clearAttachments,
  } = useComposerState(input, large);

  const referenceLabel = composerReferenceLabel(setupDraftMode);
  const submitLabel = 'Send';

  // Restore focus after an in-flight submit re-enables the textarea. Disabling
  // a focused element blurs it, and React commits the re-enable only once the
  // submit promise resolves; refocusing here, on the disabled->enabled edge,
  // lands reliably. Doing it from the submit handler instead does not: a rAF
  // scheduled there can fire before the re-enable commits and no-op on the
  // still-disabled element. This edge also covers the first send, where the
  // in-conversation composer mounts disabled and then re-enables.
  const wasDisabled = useRef(disabled);
  useEffect(() => {
    if (wasDisabled.current && !disabled) textareaRef.current?.focus();
    wasDisabled.current = disabled;
  }, [disabled, textareaRef]);

  return (
    <form
      onSubmit={event => {
        onSubmit(
          event,
          attachments.map(attachment => attachment.file),
        );
        if (input.trim()) clearAttachments();
      }}
      className={composerFormClassName(input, large, attachments.length > 0)}
    >
      <AttachmentStrip attachments={attachments} onRemove={removeAttachment} />
      <ComposerTextareaField
        input={input}
        setInput={setInput}
        disabled={disabled}
        large={large}
        referenceLabel={referenceLabel}
        textareaRef={textareaRef}
      />
      <ComposerFooter
        disabled={disabled}
        connectorsOpen={connectorsOpen}
        onToggleConnectors={() => setConnectorsOpen(open => !open)}
        sourceControlsRef={sourceControlsRef}
        fileInputRef={fileInputRef}
        onFilesChanged={onFilesChanged}
        pubmedEnabled={pubmedEnabled}
        onPubmedEnabledChange={onPubmedEnabledChange}
        submitDisabled={!input.trim() || disabled}
        submitLabel={submitLabel}
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
  return [
    COMPOSER_BASE_CLASSES,
    input.trim() ? 'has-input' : '',
    large ? HOME_COMPOSER_CLASSES : '',
    hasAttachments ? REFERENCE_COMPOSER_ATTACHED_CLASSES : '',
  ]
    .filter(Boolean)
    .join(' ');
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
function useComposerState(input: string, large: boolean) {
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

// The floating-label textarea region: the lock icon + placeholder label
// (hidden once the user has typed anything) above the auto-growing textarea.
function ComposerTextareaField({
  input,
  setInput,
  disabled,
  large,
  referenceLabel,
  textareaRef,
}: {
  input: string;
  setInput: (value: string) => void;
  disabled: boolean;
  large: boolean;
  referenceLabel: string;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
}) {
  return (
    <label className={COMPOSER_LABEL_CLASSES}>
      <span
        className={[
          COMPOSER_LABEL_TEXT_CLASSES,
          input.trim() ? COMPOSER_LABEL_TEXT_HIDDEN_CLASSES : '',
        ]
          .filter(Boolean)
          .join(' ')}
      >
        <Icon
          aria-hidden="true"
          className={COMPOSER_LABEL_ICON_CLASSES}
          name="encrypted"
        />
        {referenceLabel}
      </span>
      <textarea
        ref={textareaRef}
        // One row; the empty height comes from the textarea's min-height and
        // growth is driven by the auto-grow effect. A larger rows value would
        // force the empty box several lines tall.
        rows={1}
        value={input}
        disabled={disabled}
        className={[
          COMPOSER_TEXTAREA_CLASSES,
          large ? HOME_COMPOSER_TEXTAREA_CLASSES : '',
        ]
          .filter(Boolean)
          .join(' ')}
        onChange={e => setInput(e.target.value)}
        onKeyDown={handleComposerKeyDown}
      />
    </label>
  );
}

// The footer controls row: the file/connector source controls plus the
// submit button.
function ComposerFooter({
  disabled,
  connectorsOpen,
  onToggleConnectors,
  sourceControlsRef,
  fileInputRef,
  onFilesChanged,
  pubmedEnabled,
  onPubmedEnabledChange,
  submitDisabled,
  submitLabel,
}: {
  disabled: boolean;
  connectorsOpen: boolean;
  onToggleConnectors: () => void;
  sourceControlsRef: RefObject<HTMLDivElement | null>;
  fileInputRef: RefObject<HTMLInputElement | null>;
  onFilesChanged: (e: ChangeEvent<HTMLInputElement>) => void;
  pubmedEnabled: boolean;
  onPubmedEnabledChange?: (value: boolean) => void;
  submitDisabled: boolean;
  submitLabel: string;
}) {
  return (
    <div className={COMPOSER_ACTIONS_CLASSES}>
      <SourceControls
        disabled={disabled}
        connectorsOpen={connectorsOpen}
        onToggleConnectors={onToggleConnectors}
        sourceControlsRef={sourceControlsRef}
        fileInputRef={fileInputRef}
        onFilesChanged={onFilesChanged}
        pubmedEnabled={pubmedEnabled}
        onPubmedEnabledChange={onPubmedEnabledChange}
      />
      <button
        type="submit"
        className={tooltipClassNames({
          className: COMPOSER_SUBMIT_BUTTON_CLASSES,
          placement: 'top',
        })}
        aria-label={submitLabel}
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

// Enter submits (Shift+Enter still inserts a newline via default behavior).
function handleComposerKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    e.currentTarget.form?.requestSubmit();
  }
}
