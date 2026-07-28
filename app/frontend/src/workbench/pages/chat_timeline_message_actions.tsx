import {Icon, type IconName} from '@/components/icon';
import {copyText} from '@/lib/clipboard';
import {tooltipClassNames} from '../tooltip';
import {
  MESSAGE_ACTION_BUTTON_CLASSES,
  MESSAGE_ACTION_ICON_CLASSES,
  MESSAGE_ACTIONS_CLASSES,
  MESSAGE_ACTIONS_END_CLASSES,
} from './chat_setup_classes';

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
        align === 'end' ? MESSAGE_ACTIONS_END_CLASSES : MESSAGE_ACTIONS_CLASSES
      }
    >
      {actions.map(action => (
        <button
          key={action.label}
          type="button"
          className={tooltipClassNames({
            className: MESSAGE_ACTION_BUTTON_CLASSES,
            placement: 'top',
          })}
          aria-label={action.label}
          data-tooltip={action.label}
          onClick={action.onClick}
        >
          <Icon
            aria-hidden="true"
            className={MESSAGE_ACTION_ICON_CLASSES}
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
