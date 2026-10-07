import type {IconName} from '@/shared/ui/icon';
import {IconButton} from '@/shared/ui';
import {copyText} from '@/shared/lib/clipboard';

export interface MessageAction {
  icon: IconName;
  label: string;
  onClick?: () => void;
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
          ? 'reference-message-actions end pointer-events-none absolute top-1/2 z-[2] flex -translate-y-1/2 scale-[0.98] transition-[opacity,scale] duration-short ease-standard motion-reduce:scale-100 items-center gap-[0.2rem] border-0 bg-transparent p-[0.1rem] opacity-0 [right:calc(100%+0.4rem)] group-hover/user:pointer-events-auto group-hover/user:scale-100 group-hover/user:opacity-100 group-focus-within/user:pointer-events-auto group-focus-within/user:scale-100 group-focus-within/user:opacity-100 pointer-coarse:pointer-events-auto pointer-coarse:static pointer-coarse:mt-[0.2rem] pointer-coarse:translate-y-0 pointer-coarse:justify-end pointer-coarse:scale-100 pointer-coarse:opacity-100'
          : 'reference-message-actions flex items-center gap-[0.2rem] px-[0.2rem]'
      }
    >
      {actions.map(action => (
        <IconButton
          key={action.label}
          icon={action.icon}
          label={action.label}
          onClick={action.onClick}
        />
      ))}
    </div>
  );
}

// Omit revisions a turn no longer allows; a greyed control reads as broken.
export function responseActions(
  onRetry: (() => void) | null,
  text: string,
  filename: string,
): MessageAction[] {
  const retry: MessageAction[] = onRetry
    ? [{icon: 'refresh', label: 'Retry response', onClick: onRetry}]
    : [];
  return [
    ...retry,
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
  const edit: MessageAction[] = onEdit
    ? [{icon: 'edit', label: 'Edit prompt', onClick: onEdit}]
    : [];
  return [
    ...edit,
    {icon: 'content_copy', label: 'Copy prompt', onClick: onCopyRequest},
  ];
}
