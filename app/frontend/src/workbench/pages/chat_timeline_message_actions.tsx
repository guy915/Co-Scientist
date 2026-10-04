import {Icon, type IconName} from '@/components/icon';
import {copyText} from '@/lib/clipboard';
import {tooltipClassNames} from '../classes';

export interface MessageAction {
  icon: IconName;
  label: string;
  onClick: () => void;
}

// Revoke the download URL after handing it to the browser so blobs do not
// remain retained.
function downloadText(
  filename: string,
  text: string,
  type = 'text/markdown;charset=utf-8',
) {
  const blob = new Blob([text], {type});
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function MessageActionRow({
  actions,
  align = 'start',
}: {
  actions: MessageAction[];
  align?: 'start' | 'end';
}) {
  return (
    <div
      className={
        align === 'end'
          ? 'reference-message-actions end pointer-events-none absolute top-1/2 z-[2] flex -translate-y-1/2 scale-[0.98] items-center gap-[0.2rem] border-0 bg-transparent p-[0.1rem] opacity-0 [right:calc(100%+0.4rem)] group-hover/user:pointer-events-auto group-hover/user:scale-100 group-hover/user:opacity-100 group-focus-within/user:pointer-events-auto group-focus-within/user:scale-100 group-focus-within/user:opacity-100 pointer-coarse:pointer-events-auto pointer-coarse:static pointer-coarse:mt-[0.2rem] pointer-coarse:translate-y-0 pointer-coarse:justify-end pointer-coarse:scale-100 pointer-coarse:opacity-100'
          : 'reference-message-actions flex items-center gap-[0.2rem] px-[0.2rem]'
      }
    >
      {actions.map(action => (
        <button
          key={action.label}
          type="button"
          className={tooltipClassNames({
            className:
              'size-8 grid cursor-pointer place-items-center rounded-full border-0 bg-transparent p-0 text-cosci-muted hover:bg-cosci-hover hover:text-cosci-fg focus-visible:bg-cosci-hover focus-visible:text-cosci-fg',
            placement: 'top',
          })}
          aria-label={action.label}
          data-tooltip={action.label}
          onClick={action.onClick}
        >
          <Icon
            aria-hidden="true"
            className="text-[1.12rem]"
            name={action.icon}
          />
        </button>
      ))}
    </div>
  );
}

// Omit unavailable retries rather than show a control that appears broken.
export function responseActions(
  onRetry: (() => void) | null,
  text: string,
  filename: string,
): MessageAction[] {
  return [
    ...(onRetry
      ? [{icon: 'refresh' as const, label: 'Retry response', onClick: onRetry}]
      : []),
    {
      icon: 'content_copy',
      label: 'Copy response',
      onClick: () => void copyText(text),
    },
    {
      icon: 'download',
      label: 'Download response',
      onClick: () => downloadText(filename, text),
    },
  ];
}

export function requestActions(
  onEdit: (() => void) | null,
  onCopyRequest: () => void,
): MessageAction[] {
  return [
    ...(onEdit
      ? [{icon: 'edit' as const, label: 'Edit prompt', onClick: onEdit}]
      : []),
    {icon: 'content_copy', label: 'Copy prompt', onClick: onCopyRequest},
  ];
}
