import {
  type FormEvent,
  type ReactNode,
  useLayoutEffect,
  useRef,
  type ChangeEvent,
  useEffect,
  useState,
  type RefObject,
} from 'react';
import {Icon, type IconName} from '@/components/icon';
import {
  joinClasses,
  COMPOSER_SOURCE_ICON_CLASSES,
  tooltipClassNames,
} from '../classes';
import type {Connector, SystemStatus} from '@/api/system';
import {useSystemStatus} from '../hooks/system_status_context';

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

// Keep typing while replies stream; busy gates sending, while stoppable
// permits interruption.
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

  // Measure programmatic fills as well as typing.
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

export const REFERENCE_COMPOSER_ATTACHED_CLASSES =
  'has-attachments !min-h-[13.5rem] !pt-4';

const ATTACHMENT_STRIP_CLASSES =
  'reference-attachment-strip flex min-w-0 flex-wrap gap-[0.8rem] ' +
  'pb-[1.35rem] pointer-events-auto';

const ATTACHMENT_CARD_CLASSES =
  'reference-attachment-card group relative box-border grid h-[4.85rem] ' +
  'w-[13.75rem] flex-none items-center rounded-2xl border-0 ' +
  'bg-cosci-attach-bg py-[0.85rem] pr-[3.2rem] pl-4 ' +
  'text-cosci-attach-fg';

const ATTACHMENT_IMAGE_CARD_CLASSES =
  'reference-attachment-card reference-attachment-card--image group relative ' +
  'box-border grid size-[4.85rem] flex-none items-center overflow-hidden ' +
  'rounded-2xl border-0 bg-cosci-attach-bg p-0 ' +
  'text-cosci-attach-fg';

const ATTACHMENT_PREVIEW_IMAGE_CLASSES =
  'absolute inset-0 size-full rounded-2xl object-cover';

const ATTACHMENT_TEXT_CLASSES =
  'reference-attachment-text grid min-w-0 gap-[0.48rem]';

const ATTACHMENT_NAME_CLASSES =
  'overflow-hidden text-ellipsis whitespace-nowrap text-base font-medium ' +
  'leading-[1.15]';

const ATTACHMENT_META_CLASSES =
  'flex min-w-0 items-center gap-[0.55rem] text-[0.9rem] leading-[1.2] ' +
  'text-cosci-attach-meta';

const ATTACHMENT_EXTENSION_CLASSES =
  'reference-attachment-extension inline-grid h-[1.35rem] min-w-[1.35rem] ' +
  'place-items-center rounded-[0.18rem] bg-cosci-attach-badge ' +
  'text-[0.48rem] ' +
  'leading-none font-bold text-white';

const ATTACHMENT_REMOVE_BUTTON_CLASSES =
  'absolute top-[0.62rem] right-[0.62rem] grid size-[2.05rem] ' +
  'cursor-pointer place-items-center rounded-full border-0 ' +
  'bg-cosci-surface-raised p-0 text-cosci-fg opacity-0 ' +
  'group-hover:opacity-100 group-focus-within:opacity-100 ' +
  'pointer-coarse:opacity-100 ' +
  'hover:bg-cosci-hover focus-visible:bg-cosci-hover ' +
  'focus-visible:outline-none';

const ATTACHMENT_REMOVE_ICON_CLASSES = 'text-[1.35rem]';

export interface ComposerAttachment {
  id: string;
  file: File;
  name: string;
  badge: string;
  kind: string;
  isImage: boolean;
  previewUrl: string | null;
}

// Revoke previews on remove, clear and unmount; unreleased object URLs retain
// blobs for the document lifetime.
function revokePreview(attachment: ComposerAttachment): void {
  if (attachment.previewUrl) URL.revokeObjectURL(attachment.previewUrl);
}

// Mirror attachments in a ref so unmount cleanup sees the latest previews
// without resubscribing.
function useAttachmentPreviewCleanup(attachments: ComposerAttachment[]) {
  const attachmentRef = useRef<ComposerAttachment[]>([]);

  useEffect(() => {
    attachmentRef.current = attachments;
  }, [attachments]);

  useEffect(() => {
    return () => {
      attachmentRef.current.forEach(revokePreview);
    };
  }, []);
}

export function useComposerAttachments() {
  const [attachments, setAttachments] = useState<ComposerAttachment[]>([]);
  useAttachmentPreviewCleanup(attachments);

  // Reset the file input so picking the same file still fires change.
  function onFilesChanged(e: ChangeEvent<HTMLInputElement>) {
    const nextAttachments = Array.from(e.target.files ?? []).map(file =>
      fileToAttachment(file),
    );
    setAttachments(current => [...current, ...nextAttachments]);
    e.target.value = '';
  }

  function removeAttachment(id: string) {
    setAttachments(current => {
      const attachment = current.find(item => item.id === id);
      if (attachment) revokePreview(attachment);
      return current.filter(item => item.id !== id);
    });
  }

  function clearAttachments() {
    setAttachments(current => {
      current.forEach(revokePreview);
      return [];
    });
  }

  return {attachments, onFilesChanged, removeAttachment, clearAttachments};
}

export function AttachmentStrip({
  attachments,
  onRemove,
}: {
  attachments: ComposerAttachment[];
  onRemove: (id: string) => void;
}) {
  if (attachments.length === 0) return null;
  return (
    <div className={ATTACHMENT_STRIP_CLASSES} aria-label="Attachments">
      {attachments.map(attachment => (
        <AttachmentCard
          key={attachment.id}
          attachment={attachment}
          onRemove={onRemove}
        />
      ))}
    </div>
  );
}

function AttachmentCard({
  attachment,
  onRemove,
}: {
  attachment: ComposerAttachment;
  onRemove: (id: string) => void;
}) {
  const removeButton = (
    <AttachmentRemoveButton attachment={attachment} onRemove={onRemove} />
  );

  if (attachment.isImage && attachment.previewUrl) {
    return (
      <ImageAttachmentCard
        name={attachment.name}
        previewUrl={attachment.previewUrl}
        removeButton={removeButton}
      />
    );
  }

  return (
    <FileAttachmentCard attachment={attachment} removeButton={removeButton} />
  );
}

function ImageAttachmentCard({
  name,
  previewUrl,
  removeButton,
}: {
  name: string;
  previewUrl: string;
  removeButton: ReactNode;
}) {
  return (
    <div
      className={tooltipClassNames({
        className: ATTACHMENT_IMAGE_CARD_CLASSES,
        placement: 'top',
        wrap: true,
        alignStart: true,
      })}
      data-tooltip={name}
    >
      <img
        src={previewUrl}
        alt={name}
        className={ATTACHMENT_PREVIEW_IMAGE_CLASSES}
      />
      {removeButton}
    </div>
  );
}

function FileAttachmentCard({
  attachment,
  removeButton,
}: {
  attachment: ComposerAttachment;
  removeButton: ReactNode;
}) {
  return (
    <div
      className={tooltipClassNames({
        className: ATTACHMENT_CARD_CLASSES,
        placement: 'top',
        wrap: true,
        alignStart: true,
      })}
      data-tooltip={attachment.name}
    >
      <div className={ATTACHMENT_TEXT_CLASSES}>
        <strong className={ATTACHMENT_NAME_CLASSES}>{attachment.name}</strong>
        <span className={ATTACHMENT_META_CLASSES}>
          <span className={ATTACHMENT_EXTENSION_CLASSES}>
            {attachment.badge}
          </span>
          {attachment.kind}
        </span>
      </div>
      {removeButton}
    </div>
  );
}

function AttachmentRemoveButton({
  attachment,
  onRemove,
}: {
  attachment: ComposerAttachment;
  onRemove: (id: string) => void;
}) {
  return (
    <button
      type="button"
      className={tooltipClassNames({
        className: ATTACHMENT_REMOVE_BUTTON_CLASSES,
        placement: 'top',
      })}
      aria-label={`Remove ${attachment.name}`}
      data-tooltip={`Remove ${attachment.name}`}
      onClick={() => onRemove(attachment.id)}
    >
      <Icon
        aria-hidden="true"
        className={ATTACHMENT_REMOVE_ICON_CLASSES}
        name="close"
      />
    </button>
  );
}

function fileToAttachment(file: File): ComposerAttachment {
  const extension = fileExtension(file.name);
  const isImage = file.type.startsWith('image/');
  const suffix = Math.random().toString(36).slice(2);
  return {
    id: `${file.name}-${file.lastModified}-${suffix}`,
    file,
    name: file.name,
    badge: fileBadge(extension),
    kind: fileKind(file, extension),
    isImage,
    previewUrl: isImage ? URL.createObjectURL(file) : null,
  };
}

function fileExtension(name: string) {
  const extension = name.split('.').pop()?.trim();
  return extension ? extension.slice(0, 8).toLowerCase() : '';
}

function fileBadge(extension: string) {
  if (['md', 'mkdn', 'markdown', 'txt'].includes(extension)) return 'TXT';
  return extension ? extension.slice(0, 4).toUpperCase() : 'FILE';
}

// Markdown extensions outrank text MIME types; CSV can retain MIME-first
// classification.
const MARKDOWN_EXTENSIONS = ['md', 'mkdn', 'markdown'];

const EXTENSION_KIND_LABELS: Record<string, string> = {
  pdf: 'PDF',
  csv: 'CSV',
};

function fileKind(file: File, extension: string) {
  if (MARKDOWN_EXTENSIONS.includes(extension)) return 'Markdown';
  if (file.type.startsWith('text/') || extension === 'txt') return 'Text';
  const byExtension = EXTENSION_KIND_LABELS[extension];
  if (byExtension) return byExtension;
  return mimeSubtypeLabel(file.type);
}

function mimeSubtypeLabel(mimeType: string): string {
  return (
    mimeType
      .split('/')
      .pop()
      ?.replace(/[-+].*/, '')
      .toUpperCase() ?? 'File'
  );
}

// Only PubMed is always present; optimistic web-search display would advertise
// a deployment without a provider key.
const FALLBACK_CONNECTORS: Connector[] = [{id: 'pubmed', display: 'PubMed'}];

const WEB_SEARCH_CONNECTOR_ID = 'web_search';

export interface ConnectorToggleProps {
  pubmedEnabled: boolean;
  onPubmedEnabledChange?: (value: boolean) => void;
  webSearchEnabled: boolean;
  onWebSearchEnabledChange?: (value: boolean) => void;
}

export function useConnectorsMenu() {
  const sourceControlsRef = useRef<HTMLDivElement>(null);
  const [connectorsOpen, setConnectorsOpen] = useState(false);

  useEffect(() => {
    if (!connectorsOpen) return;

    function closeConnectors(e: globalThis.MouseEvent) {
      if (
        e.target instanceof Node &&
        sourceControlsRef.current?.contains(e.target)
      ) {
        return;
      }
      setConnectorsOpen(false);
    }

    document.addEventListener('mousedown', closeConnectors);
    return () => document.removeEventListener('mousedown', closeConnectors);
  }, [connectorsOpen]);

  return {connectorsOpen, setConnectorsOpen, sourceControlsRef};
}

interface SourceControlsProps {
  connectorsOpen: boolean;
  onToggleConnectors: () => void;
  sourceControlsRef: RefObject<HTMLDivElement | null>;
  fileInputRef: RefObject<HTMLInputElement | null>;
  onFilesChanged: (e: ChangeEvent<HTMLInputElement>) => void;
  connectors: ConnectorToggleProps;
}

export function SourceControls(props: SourceControlsProps) {
  const {
    connectorsOpen,
    onToggleConnectors,
    sourceControlsRef,
    fileInputRef,
    onFilesChanged,
    connectors,
  } = props;
  return (
    <div
      className="reference-composer-source-controls pointer-events-auto relative flex min-w-[4.6rem] items-center gap-[0.45rem]"
      ref={sourceControlsRef}
    >
      <input
        ref={fileInputRef}
        className="reference-file-input absolute size-px overflow-hidden whitespace-nowrap [clip-path:inset(50%)] [clip:rect(0_0_0_0)]"
        type="file"
        multiple
        aria-label="Upload files"
        onChange={onFilesChanged}
        tabIndex={-1}
      />
      <SourceToolbarButton
        label="Files"
        icon="add"
        onClick={() => fileInputRef.current?.click()}
      />
      <SourceToolbarButton
        label="Connectors"
        icon="database"
        expanded={connectorsOpen}
        onClick={onToggleConnectors}
      />
      {connectorsOpen ? <ConnectorsMenu connectors={connectors} /> : null}
    </div>
  );
}

// Omit aria-expanded for the non-expandable Files button.
function SourceToolbarButton({
  label,
  icon,
  expanded,
  onClick,
}: {
  label: string;
  icon: IconName;
  expanded?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={tooltipClassNames({
        className:
          'pointer-events-auto inline-flex cursor-pointer items-center justify-center rounded-full border-0 bg-transparent p-0 transition-colors enabled:hover:bg-cosci-icon-button-hover-bg enabled:focus-visible:bg-cosci-icon-button-hover-bg focus-visible:outline-none reference-composer-source-button size-8 text-cosci-source-button enabled:hover:text-cosci-source-button-hover enabled:focus-visible:text-cosci-source-button-hover aria-expanded:bg-cosci-icon-button-hover-bg aria-expanded:text-cosci-source-button-hover',
        placement: 'top',
      })}
      aria-label={label}
      aria-expanded={expanded}
      data-tooltip={label}
      onClick={onClick}
    >
      <Icon
        aria-hidden="true"
        className={COMPOSER_SOURCE_ICON_CLASSES}
        name={icon}
      />
    </button>
  );
}

function visibleConnectors(status: SystemStatus | null): Connector[] {
  // Unknown availability is different from a genuine empty deployment source
  // list.
  if (status === null) return [];
  return status.connectors?.length ? status.connectors : FALLBACK_CONNECTORS;
}

interface ConnectorBehavior {
  checked: boolean;
  setChecked?: (value: boolean) => void;
  icon: IconName;
}

function literatureBehavior(toggles: ConnectorToggleProps): ConnectorBehavior {
  return {
    checked: toggles.pubmedEnabled,
    setChecked: toggles.onPubmedEnabledChange,
    icon: 'article',
  };
}

// Web search toggles independently; the engine enables the other literature
// connectors as one stack.
const STANDALONE_BEHAVIORS: Record<
  string,
  (toggles: ConnectorToggleProps) => ConnectorBehavior
> = {
  [WEB_SEARCH_CONNECTOR_ID]: toggles => ({
    checked: toggles.webSearchEnabled,
    setChecked: toggles.onWebSearchEnabledChange,
    icon: 'search',
  }),
};

function connectorRowState(
  connector: Connector,
  toggles: ConnectorToggleProps,
): {checked: boolean; toggle: () => void; iconName: IconName} {
  const behavior = (STANDALONE_BEHAVIORS[connector.id] ?? literatureBehavior)(
    toggles,
  );
  return {
    checked: behavior.checked,
    toggle: () => behavior.setChecked?.(!behavior.checked),
    iconName: behavior.icon,
  };
}

function ConnectorMenuRow({
  connector,
  toggles,
}: {
  connector: Connector;
  toggles: ConnectorToggleProps;
}) {
  const {checked, toggle, iconName} = connectorRowState(connector, toggles);
  return (
    <button
      type="button"
      role="menuitemcheckbox"
      aria-checked={checked}
      className="reference-connectors-menu-row md-state grid min-h-[2.6rem] w-full cursor-pointer grid-cols-[1.35rem_1fr_auto] items-center gap-3 border-0 bg-transparent px-[0.9rem] py-[0.45rem] text-left font-[inherit] text-[0.9rem] text-inherit focus-visible:outline-none"
      onClick={toggle}
    >
      <Icon
        className="reference-connector-icon text-[1.15rem] text-cosci-menu-icon"
        aria-hidden="true"
        name={iconName}
      />
      <span>{connector.display}</span>
      <span
        className={joinClasses(
          'reference-toggle relative h-[0.95rem] w-[1.6rem] rounded-full after:absolute after:top-[0.15rem] after:size-[0.65rem] after:rounded-full after:[content:""]',
          checked
            ? 'bg-cosci-toggle-on-track after:right-[0.18rem] after:bg-cosci-toggle-on-knob'
            : 'bg-cosci-toggle-off-track after:left-[0.18rem] after:bg-cosci-toggle-off-knob',
        )}
        aria-hidden="true"
      />
    </button>
  );
}

function ConnectorsNote({text}: {text: string}) {
  return (
    <p
      className="reference-connectors-menu-row m-0 grid min-h-[2.6rem] w-full items-center px-[0.9rem] py-[0.45rem] text-[0.9rem] text-cosci-muted"
      role="note"
    >
      {text}
    </p>
  );
}

function ConnectorsMenuState({
  status,
  unreachable,
  visible,
}: {
  status: SystemStatus | null;
  unreachable: boolean;
  visible: number;
}) {
  if (visible > 0) return null;
  if (status !== null) {
    return <ConnectorsNote text="No sources are configured for this run." />;
  }
  if (unreachable) {
    return (
      <ConnectorsNote text="Sources unavailable — the API is unreachable." />
    );
  }
  return <ConnectorsNote text="Checking available sources…" />;
}

// Keep checking, unreachable and empty states distinct so fallback sources
// cannot misrepresent deployment availability.
function ConnectorsMenu({
  connectors: toggles,
}: {
  connectors: ConnectorToggleProps;
}) {
  const {status, unreachable} = useSystemStatus();
  const connectors = visibleConnectors(status);
  return (
    <div
      className="reference-connectors-menu pointer-events-auto absolute bottom-[2.45rem] left-[2.35rem] z-10 w-56 overflow-hidden rounded-[0.9rem] border border-cosci-menu-border bg-cosci-menu-bg py-[0.45rem] text-cosci-menu-text"
      role="menu"
      aria-label="Connectors"
    >
      <div className="reference-connectors-menu-row reference-connectors-menu-row--top grid min-h-[2.6rem] w-full grid-cols-[1fr] items-center border-0 border-b border-cosci-menu-divider bg-transparent px-[0.9rem] py-[0.45rem] font-medium text-inherit">
        <span>Connectors</span>
      </div>
      <ConnectorsMenuState
        status={status}
        unreachable={unreachable}
        visible={connectors.length}
      />
      {connectors.map(connector => (
        <ConnectorMenuRow
          key={connector.id}
          connector={connector}
          toggles={toggles}
        />
      ))}
    </div>
  );
}
