import {
  type ChangeEvent,
  type FormEvent,
  type KeyboardEvent,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from 'react';
import {Icon} from '@/components/icon';
import {tooltipClassNames} from '../tooltip';
import {
  COMPOSER_ACTIONS_CLASSES,
  COMPOSER_BASE_CLASSES,
  COMPOSER_FILE_INPUT_CLASSES,
  COMPOSER_LABEL_CLASSES,
  COMPOSER_LABEL_ICON_CLASSES,
  COMPOSER_LABEL_TEXT_CLASSES,
  COMPOSER_LABEL_TEXT_HIDDEN_CLASSES,
  COMPOSER_SOURCE_BUTTON_CLASSES,
  COMPOSER_SOURCE_CONTROLS_CLASSES,
  COMPOSER_SOURCE_ICON_CLASSES,
  COMPOSER_SUBMIT_BUTTON_CLASSES,
  COMPOSER_TEXTAREA_CLASSES,
  CONNECTOR_ICON_CLASSES,
  CONNECTOR_TOGGLE_BASE_CLASSES,
  CONNECTOR_TOGGLE_OFF_CLASSES,
  CONNECTOR_TOGGLE_ON_CLASSES,
  CONNECTORS_MENU_CLASSES,
  CONNECTORS_MENU_HEADER_CLASSES,
  CONNECTORS_MENU_ROW_CLASSES,
  HOME_COMPOSER_CLASSES,
  HOME_COMPOSER_TEXTAREA_CLASSES,
} from './chat_home_classes';

const COMPOSER_CONNECTORS = ['PubMed'];

// Auto-grow caps (px) before the textarea starts scrolling: the roomier home
// composer grows taller than the compact in-run/setup composer.
const COMPOSER_MAX_HEIGHT = 120;
const COMPOSER_MAX_HEIGHT_LARGE = 146;

// Applied when at least one attachment is present, to grow the composer's
// min-height/top-padding to fit the attachment strip above the textarea.
const REFERENCE_COMPOSER_ATTACHED_CLASSES =
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
  'hover:bg-cosci-hover focus-visible:bg-cosci-hover ' +
  'focus-visible:outline-none';

const ATTACHMENT_REMOVE_ICON_CLASSES = 'text-[1.35rem]';

// A locally-attached file (not yet uploaded/sent), derived from a browser
// File by fileToAttachment. previewUrl is a revocable object URL, only set
// for images.
interface ComposerAttachment {
  id: string;
  name: string;
  badge: string;
  kind: string;
  isImage: boolean;
  previewUrl: string | null;
}

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
  onSubmit: (e: FormEvent<HTMLFormElement>) => void;
}) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const sourceControlsRef = useRef<HTMLDivElement>(null);
  // Mirrors `attachments` for use inside the unmount-cleanup effect below,
  // which must read the latest value without re-subscribing on every change.
  const attachmentRef = useRef<ComposerAttachment[]>([]);
  const [attachments, setAttachments] = useState<ComposerAttachment[]>([]);
  const [connectorsOpen, setConnectorsOpen] = useState(false);

  // Grow the textarea with its content up to a cap, then let it scroll — the
  // reference composer expands as you type before it becomes scrollable. Runs
  // on every input change (including programmatic fills from suggestions) so the
  // height always tracks the current value; clearing the input snaps it back to
  // the CSS min-height floor.
  useLayoutEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    const maxHeight = large ? COMPOSER_MAX_HEIGHT_LARGE : COMPOSER_MAX_HEIGHT;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, maxHeight)}px`;
  }, [input, large]);

  // Enter submits (Shift+Enter still inserts a newline via default behavior).
  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      e.currentTarget.form?.requestSubmit();
    }
  }

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
      if (attachment?.previewUrl) URL.revokeObjectURL(attachment.previewUrl);
      return current.filter(item => item.id !== id);
    });
  }

  // Keeps attachmentRef current for the unmount-only cleanup effect below.
  useEffect(() => {
    attachmentRef.current = attachments;
  }, [attachments]);

  // Runs once, on unmount: revokes every remaining preview object URL so
  // navigating away doesn't leak blob URLs for attachments that were never
  // explicitly removed.
  useEffect(() => {
    return () => {
      attachmentRef.current.forEach(attachment => {
        if (attachment.previewUrl) URL.revokeObjectURL(attachment.previewUrl);
      });
    };
  }, []);

  // Closes the connectors menu on any outside mousedown while it's open; only
  // subscribes to the document listener when the menu is actually open.
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

  const referenceLabel = setupDraftMode
    ? 'Type to edit session details'
    : 'Start a new research goal to begin';
  const submitLabel = 'Send';

  return (
    <form
      onSubmit={onSubmit}
      className={[
        COMPOSER_BASE_CLASSES,
        input.trim() ? 'has-input' : '',
        large ? HOME_COMPOSER_CLASSES : '',
        attachments.length ? REFERENCE_COMPOSER_ATTACHED_CLASSES : '',
      ]
        .filter(Boolean)
        .join(' ')}
    >
      {/* Two attachment-card variants: an image card with a cropped preview,
          or a file card with name + kind badge. Both share the hover-reveal
          remove button (Escape/click elsewhere doesn't affect this). */}
      {attachments.length > 0 ? (
        <div className={ATTACHMENT_STRIP_CLASSES} aria-label="Attachments">
          {attachments.map(attachment => (
            <AttachmentCard
              key={attachment.id}
              attachment={attachment}
              onRemove={removeAttachment}
            />
          ))}
        </div>
      ) : null}
      {/* Floating label + lock icon, hidden once the user has typed
          anything (input.trim() truthy) so it doesn't overlap the text. */}
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
          onKeyDown={onKeyDown}
        />
      </label>
      <div className={COMPOSER_ACTIONS_CLASSES}>
        <div
          className={COMPOSER_SOURCE_CONTROLS_CLASSES}
          ref={sourceControlsRef}
        >
          <input
            ref={fileInputRef}
            className={COMPOSER_FILE_INPUT_CLASSES}
            type="file"
            multiple
            aria-label="Upload files"
            onChange={onFilesChanged}
            tabIndex={-1}
          />
          <button
            type="button"
            className={tooltipClassNames({
              className: COMPOSER_SOURCE_BUTTON_CLASSES,
              placement: 'top',
            })}
            aria-label="Files"
            data-tooltip="Files"
            disabled={disabled}
            onClick={() => fileInputRef.current?.click()}
          >
            <Icon
              aria-hidden="true"
              className={COMPOSER_SOURCE_ICON_CLASSES}
              name="add"
            />
          </button>
          <button
            type="button"
            className={tooltipClassNames({
              className: COMPOSER_SOURCE_BUTTON_CLASSES,
              placement: 'top',
            })}
            aria-label="Connectors"
            aria-expanded={connectorsOpen}
            data-tooltip="Connectors"
            disabled={disabled}
            onClick={() => setConnectorsOpen(open => !open)}
          >
            <Icon
              aria-hidden="true"
              className={COMPOSER_SOURCE_ICON_CLASSES}
              name="database"
            />
          </button>
          {/* Connectors menu: currently a single PubMed toggle row, closed by
              the outside-mousedown effect above. */}
          {connectorsOpen ? (
            <div
              className={CONNECTORS_MENU_CLASSES}
              role="menu"
              aria-label="Connectors"
            >
              <div className={CONNECTORS_MENU_HEADER_CLASSES}>
                <span>Connectors</span>
              </div>
              {COMPOSER_CONNECTORS.map(name => (
                <button
                  type="button"
                  role="menuitemcheckbox"
                  aria-checked={pubmedEnabled}
                  className={CONNECTORS_MENU_ROW_CLASSES}
                  key={name}
                  onClick={() => onPubmedEnabledChange?.(!pubmedEnabled)}
                >
                  <Icon
                    className={CONNECTOR_ICON_CLASSES}
                    aria-hidden="true"
                    name="article"
                  />
                  <span>{name}</span>
                  <span
                    className={[
                      CONNECTOR_TOGGLE_BASE_CLASSES,
                      pubmedEnabled
                        ? CONNECTOR_TOGGLE_ON_CLASSES
                        : CONNECTOR_TOGGLE_OFF_CLASSES,
                    ].join(' ')}
                    aria-hidden="true"
                  />
                </button>
              ))}
            </div>
          ) : null}
        </div>
        <button
          type="submit"
          className={tooltipClassNames({
            className: COMPOSER_SUBMIT_BUTTON_CLASSES,
            placement: 'top',
          })}
          aria-label={submitLabel}
          data-tooltip="Submit"
          disabled={!input.trim() || disabled}
        >
          <Icon aria-hidden="true" name="send" />
        </button>
      </div>
    </form>
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

  if (attachment.isImage && attachment.previewUrl) {
    return (
      <div
        className={tooltipClassNames({
          className: ATTACHMENT_IMAGE_CARD_CLASSES,
          placement: 'top',
          wrap: true,
          alignStart: true,
        })}
        data-tooltip={attachment.name}
      >
        <img
          src={attachment.previewUrl}
          alt={attachment.name}
          className={ATTACHMENT_PREVIEW_IMAGE_CLASSES}
        />
        {removeButton}
      </div>
    );
  }

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

// Converts a browser File into the view model rendered in the attachment
// strip, generating an id and (for images only) a previewUrl object URL that
// the caller is responsible for revoking.
function fileToAttachment(file: File): ComposerAttachment {
  const extension = fileExtension(file.name);
  const isImage = file.type.startsWith('image/');
  return {
    id: `${file.name}-${file.lastModified}-${Math.random().toString(36).slice(2)}`,
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

// Human-readable file-kind label shown next to the badge; falls back to the
// MIME subtype (stripped of any "+xml"/"-something" suffix) when the
// extension doesn't match a known kind.
function fileKind(file: File, extension: string) {
  if (['md', 'mkdn', 'markdown'].includes(extension)) return 'Markdown';
  if (file.type.startsWith('text/') || extension === 'txt') return 'Text';
  if (extension === 'pdf') return 'PDF';
  if (extension === 'csv') return 'CSV';
  return (
    file.type
      .split('/')
      .pop()
      ?.replace(/[-+].*/, '')
      .toUpperCase() ?? 'File'
  );
}
