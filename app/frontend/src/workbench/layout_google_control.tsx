import {Link} from 'react-router-dom';
import {GOOGLE_NOTE} from './audience_content';
import {
  HeaderControlTrigger,
  headerControlPopoverClasses,
  type HeaderControlProps,
} from './layout_primitives';

const POPOVER_CLASSES = headerControlPopoverClasses(
  '!w-[min(28rem,calc(100vw-2rem))]',
);

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
 */
export function GoogleTeamControl({
  open,
  onToggle,
  renderPopover,
}: HeaderControlProps) {
  return (
    <>
      <HeaderControlTrigger
        icon="rate_review"
        label={GOOGLE_NOTE.label}
        tooltip={GOOGLE_NOTE.label}
        open={open}
        onToggle={onToggle}
      />
      {open && renderPopover(<GoogleTeamNote />, POPOVER_CLASSES)}
    </>
  );
}
