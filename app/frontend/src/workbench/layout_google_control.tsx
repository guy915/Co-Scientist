import {type ReactNode} from 'react';
import {Link} from 'react-router-dom';
import {Icon} from '@/components/icon';
import {GOOGLE_NOTE} from './audience_content';
import {tooltipClassNames} from './tooltip';

const BUTTON_CLASSES =
  'ucs-logs-button relative inline-flex h-[2.35rem] min-w-max ' +
  'cursor-pointer items-center gap-[0.45rem] rounded-full border-0 ' +
  'bg-cosci-logs-accent-bg px-[0.72rem] font-[inherit] text-[0.88rem] ' +
  'font-semibold whitespace-nowrap text-cosci-logs-accent-fg ' +
  'hover:bg-cosci-logs-accent-hover ' +
  '[&[aria-expanded=true]]:bg-cosci-logs-accent-hover';

const POPOVER_CLASSES =
  'ucs-popover--logs top-[calc(100%+0.45rem)] right-0 ' +
  '!w-[min(28rem,calc(100vw-2rem))] !p-0';

/**
 * Header control replacing Logs for the Google team: a personal note and a
 * link to the recommendations page.
 *
 * @param props.open Whether the popover is shown.
 * @param props.onToggle Requests the parent flip `open`.
 * @param props.renderPopover Wraps the panel in the shell's positioned popover.
 */
export function GoogleTeamControl({
  open,
  onToggle,
  renderPopover,
}: {
  open: boolean;
  onToggle: () => void;
  renderPopover: (children: ReactNode, className: string) => ReactNode;
}) {
  return (
    <>
      <button
        type="button"
        className={tooltipClassNames({
          className: BUTTON_CLASSES,
          placement: 'left',
        })}
        data-tooltip={GOOGLE_NOTE.label}
        aria-expanded={open}
        onClick={onToggle}
        // dir on the flex container itself flips the main axis, so the icon
        // (first in the DOM) renders to the right of the Hebrew label. Set
        // here rather than on a child: direction is resolved by the flex
        // container, so a child would have no effect on the order.
        dir="rtl"
        lang="he"
      >
        <Icon
          aria-hidden="true"
          className="text-[1.05rem]"
          name="rate_review"
        />
        <span>{GOOGLE_NOTE.label}</span>
      </button>
      {open &&
        renderPopover(
          // Hebrew prose, so the panel renders RTL as a unit: text aligns
          // right, trailing punctuation lands on the correct side, and the
          // action button sits at the right edge.
          <div className="ucs-team-note" dir="rtl" lang="he">
            <p>{GOOGLE_NOTE.message}</p>
            <Link className="ucs-panel-button" to="/proposals">
              {GOOGLE_NOTE.linkLabel}
            </Link>
          </div>,
          POPOVER_CLASSES,
        )}
    </>
  );
}
