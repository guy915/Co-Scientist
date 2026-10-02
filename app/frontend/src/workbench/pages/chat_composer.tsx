import {type FormEvent, type ReactNode, useLayoutEffect, useRef} from 'react';
import {Icon} from '@/components/icon';
import {joinClasses} from '../classes';
import {tooltipClassNames} from '../tooltip';
import {
  AttachmentStrip,
  REFERENCE_COMPOSER_ATTACHED_CLASSES,
  useComposerAttachments,
} from './chat_composer_attachments';
import {
  type ConnectorToggleProps,
  SourceControls,
  useConnectorsMenu,
} from './chat_composer_connectors';

export interface ComposerProps {
  input: string;
  setInput: (value: string) => void;
  setupDraftMode?: boolean;
  busy: boolean;
  large?: boolean;
  autoFocus?: boolean;
  connectors?: ConnectorToggleProps;
  onSubmit: (e: FormEvent<HTMLFormElement>, files: File[]) => void;
  stoppable?: boolean;
  onStop?: () => void;
  placeholderOverride?: string;
  aboveInput?: ReactNode;
}

const DEFAULT_CONNECTORS: ConnectorToggleProps = {
  pubmedEnabled: true,
  webSearchEnabled: true,
};

// Keep typing available while a reply is streaming. Busy gates sending;
// stoppable lets the scientist interrupt the current reply.
export function Composer({
  input,
  setInput,
  busy,
  setupDraftMode = false,
  large = false,
  autoFocus = false,
  connectors = DEFAULT_CONNECTORS,
  onSubmit,
  stoppable = false,
  onStop,
  placeholderOverride,
  aboveInput,
}: ComposerProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const {attachments, onFilesChanged, removeAttachment, clearAttachments} =
    useComposerAttachments();
  const {connectorsOpen, setConnectorsOpen, sourceControlsRef} =
    useConnectorsMenu();
  const submitDisabled = !input.trim() || busy;
  const referenceLabel =
    placeholderOverride ||
    (setupDraftMode
      ? 'Type to edit session details'
      : 'Start a new research goal to begin');

  // Re-measure programmatic fills too; the CSS min-height sets the empty floor.
  useLayoutEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = 'auto';
    textarea.style.height = `${Math.min(textarea.scrollHeight, large ? 146 : 120)}px`;
  }, [input, large]);

  return (
    <form
      onSubmit={event => {
        onSubmit(
          event,
          attachments.map(attachment => attachment.file),
        );
        if (input.trim()) clearAttachments();
      }}
      className={joinClasses(
        'reference-composer relative mt-4 min-h-[7.9rem] rounded-[2rem] border border-cosci-composer-border bg-cosci-composer-bg p-[1.25rem_1.5rem_0.8rem]',
        input.trim() && 'has-input',
        large && 'reference-home-composer',
        attachments.length > 0 && REFERENCE_COMPOSER_ATTACHED_CLASSES,
      )}
    >
      {aboveInput}
      <AttachmentStrip attachments={attachments} onRemove={removeAttachment} />
      <label className="relative block min-h-[3.6rem] pb-[3rem]">
        <span
          className={joinClasses(
            'absolute top-0 left-[0.4rem] z-[1] flex h-6 items-center gap-[0.45rem] pointer-events-none text-base text-cosci-composer-label',
            input.trim() && 'hidden',
          )}
        >
          <Icon
            aria-hidden="true"
            className="text-[1.15rem]"
            name="encrypted"
          />
          {referenceLabel}
        </span>
        <textarea
          ref={textareaRef}
          rows={1}
          value={input}
          autoFocus={autoFocus}
          className={joinClasses(
            'relative z-[2] block min-h-[2.85rem] w-full resize-none overflow-y-auto border-0 bg-transparent p-0 font-[inherit] leading-6 text-cosci-composer-text outline-none',
            large && 'reference-home-composer-textarea',
          )}
          onChange={event => setInput(event.target.value)}
          onKeyDown={event => {
            if (event.key !== 'Enter' || event.shiftKey) return;
            event.preventDefault();
            // requestSubmit ignores a disabled submit button.
            if (!submitDisabled) event.currentTarget.form?.requestSubmit();
          }}
        />
      </label>
      <div className="reference-composer-actions pointer-events-none absolute right-5 bottom-3 left-5 flex items-end justify-between gap-3">
        <SourceControls
          connectorsOpen={connectorsOpen}
          onToggleConnectors={() => setConnectorsOpen(open => !open)}
          sourceControlsRef={sourceControlsRef}
          fileInputRef={fileInputRef}
          onFilesChanged={onFilesChanged}
          connectors={connectors}
        />
        <button
          type={stoppable ? 'button' : 'submit'}
          className={tooltipClassNames({
            className:
              'pointer-events-auto inline-flex cursor-pointer items-center justify-center rounded-full border-0 bg-transparent p-0 transition-colors enabled:hover:bg-cosci-icon-button-hover-bg enabled:focus-visible:bg-cosci-icon-button-hover-bg focus-visible:outline-none disabled:cursor-default size-8 text-cosci-source-button enabled:hover:text-cosci-source-button-hover enabled:focus-visible:text-cosci-source-button-hover disabled:text-cosci-composer-submit-disabled',
            placement: 'top',
          })}
          aria-label={stoppable ? 'Stop' : 'Send'}
          data-tooltip={stoppable ? 'Stop' : 'Submit'}
          disabled={!stoppable && submitDisabled}
          onClick={stoppable ? onStop : undefined}
        >
          <Icon
            aria-hidden="true"
            className="text-xl"
            name={stoppable ? 'stop' : 'send'}
          />
        </button>
      </div>
    </form>
  );
}
