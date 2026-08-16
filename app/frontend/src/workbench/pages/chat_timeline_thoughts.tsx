import {
  type Dispatch,
  type SetStateAction,
  useEffect,
  useId,
  useState,
} from 'react';
import {Icon} from '@/components/icon';
import {MarkdownMessage} from '@/components/markdown_message';

// Open while the Agent is still writing, collapsed once the turn is done:
// the thinking is there to be checked afterwards, not read every time.
//
// Built as a button and a panel rather than <details>/<summary>. A native
// details element hides its content outright, so opening and closing can
// only ever snap; nothing about the state change is animatable. The
// disclosure state therefore lives in React (it already did, to seed open
// from `live`) and drives the panel's own transition below.
const THOUGHTS_CLASSES = 'ucs-thoughts mt-1 mb-4';

// One label for both states, at one size. The control used to change
// shape as the turn resolved -- a pulsing "Thinking…" at one size became a
// chevroned "Thinking" at another -- which read as two different controls
// swapping places rather than as one settling.
//
// No horizontal padding: the label is the first thing in the bubble, and any
// left padding stood it inset from the reply beneath it.
const THOUGHTS_SUMMARY_CLASSES =
  'inline-flex cursor-pointer items-center gap-1 rounded-full border-0 ' +
  'bg-transparent p-0 text-left ' +
  'text-base font-medium text-cosci-muted hover:text-cosci-fg ' +
  'focus-visible:text-cosci-fg';

// The panel opens and closes by animating its grid track between 0fr and
// 1fr, which transitions to the content's own natural height without any
// measuring -- the reasoning grows the whole time a turn streams, so a
// measured max-height would be stale before it finished animating. The
// child below owns the overflow clip; this element only animates the track.
const THOUGHTS_PANEL_CLASSES =
  'grid transition-[grid-template-rows,opacity] duration-300 ease-out ' +
  'motion-reduce:transition-none';

// Pure: the panel's open/closed track and fade.
function panelStateClasses(open: boolean): string {
  return open ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0';
}

// Pure: the chevron's rotation, timed with the panel so the two read as one
// movement rather than a glyph that snaps ahead of the text it labels.
function chevronClasses(open: boolean): string {
  return (
    'text-base transition-transform duration-300 ease-out ' +
    'motion-reduce:transition-none ' +
    (open ? 'rotate-0' : 'rotate-180')
  );
}

// The thinking is rendered as markdown like any other model prose: the
// chain of thought comes back with its own paragraphs, dashes and emphasis,
// and showing that as literal characters is the same defect the reply had.
// A step smaller and grey -- no rule down the left (it is the Agent's own
// thinking, not a quotation of anything) and no height cap (a reader
// following a live turn should not have to scroll a box inside the page to
// see the end of a thought).
const THOUGHTS_BODY_CLASSES =
  'reference-thoughts-trail mt-2 max-w-[47rem] text-sm text-cosci-muted';

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
 * "Thinking" about a turn that has already landed. The button carries the
 * disclosure semantics <summary> used to give for free.
 *
 * @param live Whether the turn is still in flight.
 * @param open Whether the panel is currently open.
 * @param panelId The id of the panel this button controls.
 * @param onToggle Flips the panel open or closed.
 */
function ThoughtsSummary({
  live,
  open,
  panelId,
  onToggle,
}: {
  live: boolean;
  open: boolean;
  panelId: string;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      className={THOUGHTS_SUMMARY_CLASSES}
      aria-expanded={open}
      aria-controls={panelId}
      onClick={onToggle}
    >
      {/* The ellipsis sits inside the label rather than beside it, so the
          row's own gap does not push it off the word: it has to read as
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
        className={chevronClasses(open)}
        name="expand_more"
      />
    </button>
  );
}

/**
 * Folds the thinking away as soon as the answer starts arriving.
 *
 * The thinking is open while it is the only thing there is to watch, and the
 * first token of the reply is what makes it stale -- waiting for the turn to
 * finish left a wall of reasoning above the answer being written. Fires on
 * the transition only, so a reader who opens it back up keeps it open.
 *
 * @param answering Whether the reply has started arriving.
 * @param setOpen The disclosure's open-state setter.
 */
function useCollapseOnAnswer(
  answering: boolean,
  setOpen: Dispatch<SetStateAction<boolean>>,
) {
  useEffect(() => {
    if (answering) setOpen(false);
  }, [answering, setOpen]);
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
  return <MarkdownMessage content={trail} className={THOUGHTS_BODY_CLASSES} />;
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
 * @param answering Whether the reply has begun arriving, which folds the
 *   thinking away (see useCollapseOnAnswer).
 */
export function ThoughtsDisclosure({
  reasoning,
  live = false,
  answering,
}: {
  reasoning?: string;
  live?: boolean;
  answering?: boolean;
}) {
  const [open, setOpen] = useState(live);
  const panelId = useId();
  const trail = (reasoning ?? '').trim();
  useCollapseOnAnswer(Boolean(answering), setOpen);
  // A finished turn with no reasoning has nothing to disclose. A live one
  // shows the label from the first moment, before any thought has arrived.
  if (!live && !trail) return null;
  return (
    <div className={THOUGHTS_CLASSES}>
      <ThoughtsSummary
        live={live}
        open={open}
        panelId={panelId}
        onToggle={() => setOpen(current => !current)}
      />
      {/* `inert` while closed so a collapsed panel is out of the tab order
          and the accessibility tree, which <details> gave for free and a
          zero-height grid track does not. */}
      <div
        id={panelId}
        inert={!open}
        className={`${THOUGHTS_PANEL_CLASSES} ${panelStateClasses(open)}`}
      >
        <div className="overflow-hidden">
          <ThoughtsTrail trail={trail} />
        </div>
      </div>
    </div>
  );
}
