import {
  type ChangeEvent,
  type ReactNode,
  useEffect,
  useRef,
  useState,
} from 'react';
import {Icon} from '@/components/icon';
import {tooltipClassNames} from '../tooltip';

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
  name: string;
  badge: string;
  kind: string;
  isImage: boolean;
  previewUrl: string | null;
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
      attachmentRef.current.forEach(attachment => {
        if (attachment.previewUrl) URL.revokeObjectURL(attachment.previewUrl);
      });
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
      if (attachment?.previewUrl) URL.revokeObjectURL(attachment.previewUrl);
      return current.filter(item => item.id !== id);
    });
  }

  return {attachments, onFilesChanged, removeAttachment};
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
