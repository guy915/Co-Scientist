import {useState} from 'react';
import {Icon} from '@/components/icon';

// Open while the Agent is still writing, collapsed once the turn is done:
// the thinking is there to be checked afterwards, not read every time. The
// marker is suppressed so the summary can carry its own chevron.
const THOUGHTS_CLASSES = 'ucs-thoughts group mt-1 mb-2 [&>summary]:list-none';

// One summary for both states, at one size. The control used to change
// shape as the turn resolved -- a pulsing "Thinking…" at one size became a
// chevroned "Thinking" at another -- which read as two different controls
// swapping places rather than as one settling.
const THOUGHTS_SUMMARY_CLASSES =
  'inline-flex cursor-pointer items-center gap-1 rounded-full px-1 ' +
  'text-sm font-medium text-cosci-muted hover:text-cosci-fg ' +
  'focus-visible:text-cosci-fg';

// Reasoning is plain text, not markdown, so it keeps `whitespace-pre-wrap`:
// the model's own line breaks are the only structure it has. Just text, a
// step smaller and grey -- no rule down the left (it is the Agent's own
// thinking, not a quotation of anything) and no height cap (a reader
// following a live turn should not have to scroll a box inside the page to
// see the end of a thought).
const THOUGHTS_BODY_CLASSES =
  'reference-thoughts-trail mt-2 max-w-[47rem] text-sm leading-relaxed ' +
  'whitespace-pre-wrap text-cosci-muted';

// The disclosure chevron, trailing the label and the ellipsis. It points
// down while the panel is open -- which is its default, and the state a live
// turn is in -- and flips up when the thinking is folded away. Rotated
// rather than swapped for a second glyph so both states are one shape.
const THOUGHTS_CHEVRON_CLASSES =
  'text-sm transition-transform duration-150 rotate-180 group-open:rotate-0';

/**
 * The counting ellipsis shown while the Agent is still thinking.
 *
 * Three ordinary periods in the label's own type, fading in one at a time
 * and starting over, so the label reads as live work rather than a stalled
 * one. Decorative: the word beside them is what gets announced.
 */
function ThinkingDots() {
  return (
    <span className="reference-thinking-dots" aria-hidden="true">
      <span>.</span>
      <span>.</span>
      <span>.</span>
    </span>
  );
}

/**
 * The disclosure's label row: the word, the dots while live, the chevron.
 *
 * Only the live state announces itself. The finished disclosure renders the
 * same word, and a screen reader meeting it as a status update would hear
 * "Thinking" about a turn that has already landed.
 */
function ThoughtsSummary({live}: {live: boolean}) {
  return (
    <summary className={THOUGHTS_SUMMARY_CLASSES}>
      {/* The ellipsis sits inside the label rather than beside it, so the
          summary's own gap does not push it off the word: it has to read as
          "Thinking..." and not as a word followed by three loose periods. */}
      <span
        role={live ? 'status' : undefined}
        aria-live={live ? 'polite' : undefined}
      >
        Thinking
        {live && <ThinkingDots />}
      </span>
      <Icon
        aria-hidden="true"
        className={THOUGHTS_CHEVRON_CLASSES}
        name="expand_more"
      />
    </summary>
  );
}

/**
 * The chain of thought itself: plain running text that grows with the turn.
 *
 * It used to live in a capped, scrolling box, which meant following a live
 * turn required scrolling a panel inside the scrolling page. It now flows
 * with the timeline, which already follows the newest content. Renders
 * nothing until the first fragment lands, so a live turn does not open on an
 * empty block.
 *
 * @param trail The reasoning written so far.
 */
function ThoughtsTrail({trail}: {trail: string}) {
  if (!trail) return null;
  return <div className={THOUGHTS_BODY_CLASSES}>{trail}</div>;
}

/**
 * One turn's chain of thought, live while the Agent writes and collapsed
 * under the message once it lands.
 *
 * The live trail used to disappear the instant the reply arrived, which threw
 * away the one part of the turn that explains it. Keeping the reasoning here
 * means a scientist can go back to why the Agent asked what it asked -- and
 * mirrors the transcript the model itself is given, which now carries the
 * same reasoning.
 *
 * Seeding the open state from `live` works because the two states are
 * separate mounts: the live trail is its own timeline item, replaced by the
 * finished disclosure inside the bubble. `live` never flips under a reader
 * who has toggled the panel themselves, so this state never has to reconcile
 * one against the other.
 *
 * @param reasoning The chain of thought, as far as it has been written.
 * @param live Whether the turn producing it is still in flight.
 */
export function ThoughtsDisclosure({
  reasoning,
  live = false,
}: {
  reasoning?: string;
  live?: boolean;
}) {
  const [open, setOpen] = useState(live);
  const trail = (reasoning ?? '').trim();
  // A finished turn with no reasoning has nothing to disclose. A live one
  // shows the label from the first moment, before any thought has arrived.
  if (!live && !trail) return null;
  return (
    <details
      className={THOUGHTS_CLASSES}
      open={open}
      onToggle={event => setOpen(event.currentTarget.open)}
    >
      <ThoughtsSummary live={live} />
      <ThoughtsTrail trail={trail} />
    </details>
  );
}
