import {
  type Dispatch,
  type SetStateAction,
  useEffect,
  useId,
  useState,
} from 'react';
import {Icon} from '@/components/icon';
import {MarkdownMessage} from '@/components/markdown_message';

function panelStateClasses(open: boolean): string {
  return open ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0';
}

function chevronClasses(open: boolean): string {
  return (
    'text-base transition-transform duration-300 ease-out ' +
    'motion-reduce:transition-none ' +
    (open ? 'rotate-0' : 'rotate-180')
  );
}

// The ellipsis is decorative; its neighboring word is what assistive
// technology announces.
function ThinkingDots() {
  return (
    <span className="reference-thinking-dots" aria-hidden="true">
      <span>.</span>
      <span>.</span>
      <span>.</span>
    </span>
  );
}

// Announce only live thinking; settled disclosures must not sound like work
// still in progress.
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
      className="inline-flex cursor-pointer items-center gap-1 rounded-full border-0 bg-transparent p-0 text-left text-base font-medium text-cosci-muted hover:text-cosci-fg focus-visible:text-cosci-fg"
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

// Collapse only when prose first arrives so a reader who reopens reasoning
// keeps it open.
function useCollapseOnAnswer(
  answering: boolean,
  setOpen: Dispatch<SetStateAction<boolean>>,
) {
  useEffect(() => {
    if (answering) setOpen(false);
  }, [answering, setOpen]);
}

function ThoughtsTrail({trail}: {trail: string}) {
  if (!trail) return null;
  return (
    // Let reasoning flow in the page rather than require nested scrolling.
    <MarkdownMessage
      content={trail}
      className="reference-thoughts-trail mt-2 max-w-[47rem] text-sm text-cosci-muted"
    />
  );
}

// Live and finished trails mount separately, so seeding from live cannot
// override a reader's disclosure choice.
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
  if (!live && !trail) return null;
  return (
    // Use a button and panel because native details hides content without an
    // animatable transition.
    <div className="ucs-thoughts mt-1 mb-4">
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
        // Animate the grid track to natural height; streamed reasoning makes measured
        // max-height stale.
        className={`grid transition-[grid-template-rows,opacity] duration-300 ease-out motion-reduce:transition-none ${panelStateClasses(open)}`}
      >
        <div className="overflow-hidden">
          <ThoughtsTrail trail={trail} />
        </div>
      </div>
    </div>
  );
}
