import {type ReactNode} from 'react';
import {Link} from 'react-router-dom';
import {Icon} from '@/components/icon';
import {GOOGLE_NOTE} from './audience_content';
import {
  headerControlButtonClasses,
  headerControlPopoverClasses,
} from './layout_primitives';
import {tooltipClassNames} from './tooltip';

const BUTTON_CLASSES = headerControlButtonClasses();

const POPOVER_CLASSES = headerControlPopoverClasses(
  '!w-[min(28rem,calc(100vw-2rem))]',
);

// The trigger button on its own: a labelled pill with a review icon.
function GoogleTeamTriggerButton({
  open,
  onToggle,
}: {
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      className={tooltipClassNames({
        className: BUTTON_CLASSES,
        placement: 'left',
      })}
      data-tooltip={GOOGLE_NOTE.label}
      aria-expanded={open}
      onClick={onToggle}
    >
      <Icon aria-hidden="true" className="text-[1.05rem]" name="rate_review" />
      <span>{GOOGLE_NOTE.label}</span>
    </button>
  );
}

// The popover body: the RTL Hebrew note plus its action links.
function GoogleTeamNote() {
  return (
    // Hebrew prose, so the panel renders RTL as a unit: text aligns right,
    // trailing punctuation lands on the correct side, and the action button
    // sits at the right edge.
    <div className="ucs-team-note" dir="rtl" lang="he">
      <p>{GOOGLE_NOTE.message}</p>
      {/* Under dir="rtl" the row reads right to left, so the suggestions
          link stays where it was, "about me" sits beside it, and contact
          lands on the left. */}
      <div className="ucs-team-note-actions">
        <Link className="ucs-panel-button" to="/proposals">
          {GOOGLE_NOTE.linkLabel}
        </Link>
        <a
          className="ucs-panel-button is-tonal"
          href={GOOGLE_NOTE.aboutUrl}
          target="_blank"
          rel="noreferrer"
        >
          {GOOGLE_NOTE.aboutLabel}
        </a>
        <a
          className="ucs-panel-button is-tonal"
          href={GOOGLE_NOTE.contactUrl}
          target="_blank"
          rel="noreferrer"
        >
          {GOOGLE_NOTE.contactLabel}
        </a>
      </div>
    </div>
  );
}

/**
 * Header control replacing Logs for the Google team: a personal note and a
 * link to the recommendations page.
 *
 * @param props.open Whether the popover is shown.
 * @param props.onToggle Requests the parent flip `open`.
 * @param props.renderPopover Wraps the panel in the shell's positioned popover.
 */
interface GoogleTeamControlProps {
  open: boolean;
  onToggle: () => void;
  renderPopover: (children: ReactNode, className: string) => ReactNode;
}

export function GoogleTeamControl({
  open,
  onToggle,
  renderPopover,
}: GoogleTeamControlProps) {
  return (
    <>
      <GoogleTeamTriggerButton open={open} onToggle={onToggle} />
      {open && renderPopover(<GoogleTeamNote />, POPOVER_CLASSES)}
    </>
  );
}
