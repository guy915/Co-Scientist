import {type ReactNode} from 'react';
import {Icon} from '@/components/icon';
import {PILOT_FEEDBACK_EMAIL, PILOT_GUIDE} from './audience_content';
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
 * Header control replacing Logs for SBI/UCD: an early-access pilot guide.
 *
 * @param props.open Whether the popover is shown.
 * @param props.onToggle Requests the parent flip `open`.
 * @param props.renderPopover Wraps the panel in the shell's positioned popover.
 */
export function PilotControl({
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
        data-tooltip="Early access"
        aria-expanded={open}
        onClick={onToggle}
      >
        <Icon aria-hidden="true" className="text-[1.05rem]" name="stars" />
        <span>Early access</span>
      </button>
      {open &&
        renderPopover(
          <div className="grid gap-3 p-4">
            <h2 className="text-base font-semibold">{PILOT_GUIDE.title}</h2>
            <p className="text-cosci-muted">{PILOT_GUIDE.intro}</p>
            <div>
              <h3 className="font-semibold">Try these</h3>
              <ul className="list-disc pl-5">
                {PILOT_GUIDE.tryThese.map(item => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
            <div>
              <h3 className="font-semibold">Known limitations</h3>
              <ul className="list-disc pl-5">
                {PILOT_GUIDE.limitations.map(item => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
            <a
              className="text-cosci-primary underline"
              href={`mailto:${PILOT_FEEDBACK_EMAIL}?subject=Co-Scientist%20pilot%20feedback`}
            >
              Send feedback
            </a>
          </div>,
          POPOVER_CLASSES,
        )}
    </>
  );
}
