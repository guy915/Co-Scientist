import {Icon, type IconName} from '@/components/icon';
import {copyText} from '@/lib/clipboard';
import {tooltipClassNames} from '../classes';

/**
 * One icon-button entry in a {@link MessageActionRow} (e.g.
 * retry/copy/download).
 */
export interface MessageAction {
  icon: IconName;
  label: string;
  onClick: () => void;
}

// Triggers a browser file download for arbitrary text content by wrapping it
// in a Blob, pointing a throwaway anchor at an object URL, and programmatically
// clicking it; the object URL is revoked immediately after since the download
// has already been handed off to the browser.
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

/**
 * Renders a row of icon-button actions under a message/card. `align: 'end'`
 * switches to the floating, hover-revealed treatment used for a user bubble's
 * edit/copy row (MESSAGE_ACTIONS_END_CLASSES); `align: 'start'` (default) is
 * the plain inline row used under assistant responses and cards.
 *
 * @param actions The icon-button actions to render, in order.
 * @param align Row treatment: `'end'` for the floating user-bubble row,
 *   `'start'` for the plain inline row.
 */
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

/**
 * Builds the retry/copy/download action set shown under an assistant response.
 *
 * @param onRetry Handler for regenerating the response, or null when this
 *   response cannot be regenerated. Omitted rather than shown inert: a retry
 *   control that answers a click with nothing is indistinguishable from one
 *   that is broken.
 * @param text The response text to copy or download.
 * @param filename Download filename for the response.
 * @returns The action array for a MessageActionRow.
 */
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

/**
 * Builds the edit/copy action set shown under a user request bubble.
 *
 * @param onEdit Handler to open the message for editing, or null when this
 *   prompt has no durable turn behind it to revise.
 * @param onCopyRequest Handler to copy the message's text.
 * @returns The action array for a MessageActionRow.
 */
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
