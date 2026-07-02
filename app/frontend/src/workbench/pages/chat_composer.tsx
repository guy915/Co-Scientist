import {
  type ChangeEvent,
  type FormEvent,
  type KeyboardEvent,
  useEffect,
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

const REFERENCE_COMPOSER_ATTACHED_CLASSES =
  'has-attachments !min-h-[13.5rem] !pt-4';

const ATTACHMENT_STRIP_CLASSES =
  'reference-attachment-strip flex min-w-0 gap-[0.8rem] overflow-x-auto ' +
  'pb-[1.35rem] pointer-events-auto [scrollbar-width:none] ' +
  '[&::-webkit-scrollbar]:hidden';

const ATTACHMENT_CARD_CLASSES =
  'reference-attachment-card group relative box-border grid h-[4.85rem] ' +
  'w-[13.75rem] flex-none items-center rounded-2xl border-0 bg-[#eef2f8] ' +
  'py-[0.85rem] pr-[3.2rem] pl-4 text-[#202124] dark:bg-[#303335] ' +
  'dark:text-[#f1f3f4]';

const ATTACHMENT_IMAGE_CARD_CLASSES =
  'reference-attachment-card reference-attachment-card--image group relative ' +
  'box-border grid size-[4.85rem] flex-none items-center overflow-hidden ' +
  'rounded-2xl border-0 bg-[#eef2f8] p-0 text-[#202124] dark:bg-[#303335] ' +
  'dark:text-[#f1f3f4]';

const ATTACHMENT_PREVIEW_IMAGE_CLASSES = 'block size-full object-cover';

const ATTACHMENT_TEXT_CLASSES =
  'reference-attachment-text grid min-w-0 gap-[0.48rem]';

const ATTACHMENT_NAME_CLASSES =
  'overflow-hidden text-ellipsis whitespace-nowrap text-base font-medium ' +
  'leading-[1.15]';

const ATTACHMENT_META_CLASSES =
  'flex min-w-0 items-center gap-[0.55rem] text-[0.9rem] leading-[1.2] ' +
  'text-[#202124] dark:text-[#e8eaed]';

const ATTACHMENT_EXTENSION_CLASSES =
  'reference-attachment-extension inline-grid h-[1.35rem] min-w-[1.35rem] ' +
  'place-items-center rounded-[0.18rem] bg-[#7d8797] text-[0.48rem] ' +
  'leading-none font-bold text-white';

const ATTACHMENT_REMOVE_BUTTON_CLASSES =
  'absolute top-[0.62rem] right-[0.62rem] grid size-[2.05rem] ' +
  'cursor-pointer place-items-center rounded-full border-0 bg-white p-0 ' +
  'text-[#3c4043] opacity-0 group-hover:opacity-100 ' +
  'group-focus-within:opacity-100 hover:bg-[#f8fafd] ' +
  'focus-visible:bg-[#f8fafd] focus-visible:outline-none dark:bg-[#202124] ' +
  'dark:text-[#e8eaed] dark:hover:bg-[#3c4043] ' +
  'dark:focus-visible:bg-[#3c4043]';

const ATTACHMENT_REMOVE_ICON_CLASSES = 'text-[1.35rem]';

interface ComposerAttachment {
  id: string;
  name: string;
  badge: string;
  kind: string;
  isImage: boolean;
  previewUrl: string | null;
}

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
  const sourceControlsRef = useRef<HTMLDivElement>(null);
  const attachmentRef = useRef<ComposerAttachment[]>([]);
  const [attachments, setAttachments] = useState<ComposerAttachment[]>([]);
  const [connectorsOpen, setConnectorsOpen] = useState(false);

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      e.currentTarget.form?.requestSubmit();
    }
  }

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
      if (attachment?.previewUrl) URL.revokeObjectURL(attachment.previewUrl);
      return current.filter(item => item.id !== id);
    });
  }

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
      {attachments.length > 0 ? (
        <div className={ATTACHMENT_STRIP_CLASSES} aria-label="Attachments">
          {attachments.map(attachment =>
            attachment.isImage && attachment.previewUrl ? (
              <div
                className={tooltipClassNames({
                  className: ATTACHMENT_IMAGE_CARD_CLASSES,
                  placement: 'top',
                  wrap: true,
                })}
                key={attachment.id}
                data-tooltip={attachment.name}
              >
                <img
                  src={attachment.previewUrl}
                  alt={attachment.name}
                  className={ATTACHMENT_PREVIEW_IMAGE_CLASSES}
                />
                <button
                  type="button"
                  className={tooltipClassNames({
                    className: ATTACHMENT_REMOVE_BUTTON_CLASSES,
                    placement: 'top',
                  })}
                  aria-label={`Remove ${attachment.name}`}
                  data-tooltip={`Remove ${attachment.name}`}
                  onClick={() => removeAttachment(attachment.id)}
                >
                  <Icon
                    aria-hidden="true"
                    className={ATTACHMENT_REMOVE_ICON_CLASSES}
                    name="close"
                  />
                </button>
              </div>
            ) : (
              <div
                className={tooltipClassNames({
                  className: ATTACHMENT_CARD_CLASSES,
                  placement: 'top',
                  wrap: true,
                })}
                key={attachment.id}
                data-tooltip={attachment.name}
              >
                <div className={ATTACHMENT_TEXT_CLASSES}>
                  <strong className={ATTACHMENT_NAME_CLASSES}>
                    {attachment.name}
                  </strong>
                  <span className={ATTACHMENT_META_CLASSES}>
                    <span className={ATTACHMENT_EXTENSION_CLASSES}>
                      {attachment.badge}
                    </span>
                    {attachment.kind}
                  </span>
                </div>
                <button
                  type="button"
                  className={tooltipClassNames({
                    className: ATTACHMENT_REMOVE_BUTTON_CLASSES,
                    placement: 'top',
                  })}
                  aria-label={`Remove ${attachment.name}`}
                  data-tooltip={`Remove ${attachment.name}`}
                  onClick={() => removeAttachment(attachment.id)}
                >
                  <Icon
                    aria-hidden="true"
                    className={ATTACHMENT_REMOVE_ICON_CLASSES}
                    name="close"
                  />
                </button>
              </div>
            ),
          )}
        </div>
      ) : null}
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
            name="shield"
          />
          {referenceLabel}
        </span>
        <textarea
          rows={large ? 4 : 3}
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

function fileExtension(name: string) {
  const extension = name.split('.').pop()?.trim();
  return extension ? extension.slice(0, 8).toLowerCase() : '';
}

function fileBadge(extension: string) {
  if (['md', 'mkdn', 'markdown', 'txt'].includes(extension)) return 'TXT';
  return extension ? extension.slice(0, 4).toUpperCase() : 'FILE';
}

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
