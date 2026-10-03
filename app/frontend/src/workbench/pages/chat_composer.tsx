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

/**
 * Applied to the composer form when at least one attachment is present, to
 * grow the composer's min-height/top-padding to fit the attachment strip
 * above the textarea.
 */
export const REFERENCE_COMPOSER_ATTACHED_CLASSES =
  'has-attachments !min-h-[13.5rem] !pt-4';

// Attachment strip/card styling family: the flex-wrap strip above the
// textarea, the file-card and image-card variants inside it (name/badge/kind
// for files, a cropped preview for images), and the hover-revealed remove
// button shared by both variants.
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

/**
 * A locally-attached file (not yet uploaded/sent), derived from a browser
 * File by fileToAttachment. previewUrl is a revocable object URL, only set
 * for images.
 */
export interface ComposerAttachment {
  id: string;
  file: File;
  name: string;
  badge: string;
  kind: string;
  isImage: boolean;
  previewUrl: string | null;
}

// Releases an attachment's preview object URL, if it has one. Every path that
// drops an attachment (removing one, clearing them all, unmounting) goes
// through here, since a preview left un-revoked leaks its blob for the life of
// the document.
function revokePreview(attachment: ComposerAttachment): void {
  if (attachment.previewUrl) URL.revokeObjectURL(attachment.previewUrl);
}

// Revokes every remaining preview object URL on unmount, via a ref mirroring
// `attachments`, so navigating away doesn't leak blob URLs for attachments
// that were never explicitly removed.
function useAttachmentPreviewCleanup(attachments: ComposerAttachment[]) {
  // Mirrors `attachments` for use inside the unmount-only effect below, which
  // must read the latest value without re-subscribing on every change.
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

/**
 * Owns the staged-attachments list: appending newly picked files and
 * removing one by id (revoking its preview object URL), plus the cleanup
 * that revokes any remaining preview object URLs on unmount.
 */
export function useComposerAttachments() {
  const [attachments, setAttachments] = useState<ComposerAttachment[]>([]);
  useAttachmentPreviewCleanup(attachments);

  // Appends newly picked files as attachments and resets the file input so
  // selecting the same file again still fires a change event.
  function onFilesChanged(e: ChangeEvent<HTMLInputElement>) {
    const nextAttachments = Array.from(e.target.files ?? []).map(file =>
      fileToAttachment(file),
    );
    setAttachments(current => [...current, ...nextAttachments]);
    e.target.value = '';
  }

  // Drops one attachment by id, revoking its preview object URL (if any) to
  // avoid leaking blob memory.
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

/**
 * Renders the staged-attachments strip above the textarea, or nothing when
 * there are none. Two attachment-card variants render inside: an image card
 * with a cropped preview, or a file card with name + kind badge; both share
 * the hover-reveal remove button (see AttachmentCard).
 */
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

// Renders one staged attachment: an image card with a cropped preview, or a
// file card with name + kind badge. Both variants share the same hover-reveal
// remove button.
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

// Image attachment-card variant: a cropped preview plus the shared remove
// button.
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

// File attachment-card variant: name + kind badge plus the shared remove
// button.
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

// The hover-revealed remove button shared by both attachment-card variants.
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

// Converts a browser File into the view model rendered in the attachment
// strip, generating an id and (for images only) a previewUrl object URL that
// the caller is responsible for revoking.
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

// Lower-cased extension from a filename, capped to 8 chars (defends against
// pathological "filenames" with no real extension).
function fileExtension(name: string) {
  const extension = name.split('.').pop()?.trim();
  return extension ? extension.slice(0, 8).toLowerCase() : '';
}

// Short badge shown on the attachment card (e.g. "PDF", "TXT"); markdown/text
// extensions are normalized to "TXT".
function fileBadge(extension: string) {
  if (['md', 'mkdn', 'markdown', 'txt'].includes(extension)) return 'TXT';
  return extension ? extension.slice(0, 4).toUpperCase() : 'FILE';
}

// Extensions whose label wins outright, regardless of MIME type — checked
// before the text/ MIME check below (a markdown file can be served as
// text/markdown, which must still read "Markdown", not "Text").
const MARKDOWN_EXTENSIONS = ['md', 'mkdn', 'markdown'];

// Extension -> label for kinds resolved only after the text/ MIME check
// below has had first refusal (e.g. a .csv served as text/plain reads
// "Text", matching the MIME-first precedence of the original checks).
const EXTENSION_KIND_LABELS: Record<string, string> = {
  pdf: 'PDF',
  csv: 'CSV',
};

// Human-readable file-kind label shown next to the badge; falls back to the
// MIME subtype (stripped of any "+xml"/"-something" suffix) when neither the
// extension nor the MIME type matches a known kind.
function fileKind(file: File, extension: string) {
  if (MARKDOWN_EXTENSIONS.includes(extension)) return 'Markdown';
  if (file.type.startsWith('text/') || extension === 'txt') return 'Text';
  const byExtension = EXTENSION_KIND_LABELS[extension];
  if (byExtension) return byExtension;
  return mimeSubtypeLabel(file.type);
}

// Uppercased MIME subtype (e.g. "image/svg+xml" -> "SVG"), or "File" when the
// type string doesn't parse.
function mimeSubtypeLabel(mimeType: string): string {
  return (
    mimeType
      .split('/')
      .pop()
      ?.replace(/[-+].*/, '')
      .toUpperCase() ?? 'File'
  );
}

// Shown until /status responds (and if it reports none), so the menu is never
// empty. Only PubMed belongs here: it is the always-present literature base,
// whereas web search exists only when the MCP server has a provider key.
// Listing web search optimistically would flash a connector that a deployment
// without a key does not actually have.
const FALLBACK_CONNECTORS: Connector[] = [{id: 'pubmed', display: 'PubMed'}];

// The connector id whose row drives the standalone web-search toggle; every
// other id shares the literature toggle (see ConnectorsMenu).
const WEB_SEARCH_CONNECTOR_ID = 'web_search';

/**
 * The PubMed/web-search connector toggle values plus their change callbacks,
 * bundled so SourceControls/ConnectorsMenu can each take a
 * single argument instead of four.
 */
export interface ConnectorToggleProps {
  pubmedEnabled: boolean;
  onPubmedEnabledChange?: (value: boolean) => void;
  webSearchEnabled: boolean;
  onWebSearchEnabledChange?: (value: boolean) => void;
}

/**
 * Owns the connectors-menu open flag and the outside-mousedown listener that
 * closes it; only subscribes to the document listener when the menu is
 * actually open.
 */
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

// Props for SourceControls, named at module level per the destructured
// prop signature otherwise pushing the component past the line cap.
interface SourceControlsProps {
  connectorsOpen: boolean;
  onToggleConnectors: () => void;
  sourceControlsRef: RefObject<HTMLDivElement | null>;
  fileInputRef: RefObject<HTMLInputElement | null>;
  onFilesChanged: (e: ChangeEvent<HTMLInputElement>) => void;
  connectors: ConnectorToggleProps;
}

/**
 * Renders the composer's file/connector toolbar row: the hidden file input
 * and its trigger button, the Connectors button, and (while open) the
 * connectors menu with its connector toggle rows.
 */
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

// One toolbar trigger button in the source-controls row (Files, Connectors):
// an icon button with a shared tooltip/label. `expanded` is only set by the
// Connectors button; leaving it undefined for Files omits aria-expanded
// entirely, matching a plain non-expandable button.
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

// The available data sources come from the backend (/status), derived from
// literature and web-search availability plus the configured tools YAML, so
// newly configured connectors appear here automatically.
function visibleConnectors(status: SystemStatus | null): Connector[] {
  // No answer yet is not the same as an empty answer: the caller renders its
  // own note for that, rather than this passing off the fallback as the
  // deployment's real source list.
  if (status === null) return [];
  return status.connectors?.length ? status.connectors : FALLBACK_CONNECTORS;
}

// Which toggle a connector row reads and writes, plus the icon it shows.
interface ConnectorBehavior {
  checked: boolean;
  setChecked?: (value: boolean) => void;
  icon: IconName;
}

// The shared pubmed/literature-retrieval behavior, for every connector with
// no entry of its own.
function literatureBehavior(toggles: ConnectorToggleProps): ConnectorBehavior {
  return {
    checked: toggles.pubmedEnabled,
    setChecked: toggles.onPubmedEnabledChange,
    icon: 'article',
  };
}

// The connectors that own an independent toggle, keyed by id. Web search
// stands alone here; every other connector falls through to the literature
// default above, since the engine enables that stack as one unit. This maps
// ids that are already on screen to their behavior — which connectors are
// shown at all is decided by visibleConnectors alone.
//
// Entries are selector functions, not built behaviors, so the table itself
// lives at module scope: a per-row table meant rebuilding every connector's
// behavior on every render just to read one of them back out.
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

// One connector row's derived checked/toggle/icon state, from a single
// lookup in the table above.
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

// One row in the connectors menu: an icon, the connector's display name, and
// its on/off toggle pill.
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

// A non-row line in the menu: the states that are not a connector list, and
// must not read as one.
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

// The note shown in place of rows, or nothing when there are rows to show.
// A menu with no rows and no explanation is the one outcome to avoid: it
// looks like the list failed to load however it got there.
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

/**
 * The connectors menu: a header plus one ConnectorMenuRow per visible
 * connector. Closed by the outside-mousedown effect in the parent composer
 * (see useConnectorsMenu).
 *
 * The three states are kept apart on purpose. "Still checking" and "could not
 * check" both used to render the PubMed-only fallback, which is a claim about
 * the deployment -- a scientist reading it has no way to tell an unreachable
 * API from a backend that genuinely advertises one source.
 */
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
