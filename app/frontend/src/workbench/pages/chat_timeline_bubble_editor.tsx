import {useEffect, useRef, useState, type KeyboardEvent} from 'react';

// The user bubble's own shape (radii, fill, padding) so the prompt is edited
// where it sits -- but stacking rather than a flex row, and wider, because it
// is being written in rather than read. Spelled out instead of composed from
// USER_BUBBLE_CLASSES: that constant carries `flex`, and whether a `block`
// appended after it wins depends on Tailwind's output order, not the string's.
const EDITOR_BUBBLE_CLASSES =
  'reference-user-bubble-editor block w-[36rem] max-w-full ' +
  'rounded-tl-[26px] rounded-tr-[4px] rounded-br-[26px] rounded-bl-[26px] ' +
  'bg-cosci-user-bubble-bg px-4 py-3 text-base leading-[1.45] text-cosci-fg';

const EDITOR_TEXTAREA_CLASSES =
  'block w-full resize-none border-0 bg-transparent p-0 text-base ' +
  'leading-[1.45] text-cosci-fg outline-none';

const EDITOR_ACTIONS_CLASSES = 'mt-3 flex justify-end gap-2';

// Compact against the plan card's buttons: this row sits inside a message,
// not under a document.
const EDITOR_BUTTON_CLASSES =
  'min-h-[2.1rem] cursor-pointer rounded-full border px-4 text-sm font-medium';

const EDITOR_CANCEL_CLASSES =
  `${EDITOR_BUTTON_CLASSES} border-cosci-btn-secondary-border ` +
  'bg-transparent text-cosci-btn-secondary-fg ' +
  'hover:bg-cosci-btn-secondary-hover-bg';

const EDITOR_SEND_CLASSES =
  `${EDITOR_BUTTON_CLASSES} border-cosci-btn-primary-bg ` +
  'bg-cosci-btn-primary-bg text-cosci-btn-primary-fg ' +
  'hover:bg-cosci-btn-primary-hover disabled:cursor-default ' +
  'disabled:border-cosci-btn-disabled-border ' +
  'disabled:bg-cosci-btn-disabled-bg disabled:text-cosci-btn-disabled-fg';

// Grows the textarea to its content so a long prompt is editable whole,
// rather than through a three-line porthole.
function fitToContent(node: HTMLTextAreaElement | null): void {
  if (!node) return;
  node.style.height = 'auto';
  node.style.height = `${node.scrollHeight}px`;
}

/**
 * Edits one already-sent prompt in place.
 *
 * The prompt is revised where it stands rather than being loaded back into
 * the composer: the composer's job is the next thing to say, so putting an
 * old message there loses which message is being changed, and sending it
 * appends a second prompt instead of correcting the first. Submitting here
 * replaces the turn and everything the Agent derived from it.
 *
 * @param initial The prompt's current text.
 * @param onCancel Leaves the prompt as it was.
 * @param onSubmit Receives the revised text; only called when it changed.
 */
export function BubbleEditor({
  initial,
  onCancel,
  onSubmit,
}: {
  initial: string;
  onCancel: () => void;
  onSubmit: (content: string) => void;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const [value, setValue] = useState(initial);
  const changed = value.trim() !== '' && value.trim() !== initial.trim();

  // Opens focused with the caret at the end, sized to the prompt: editing
  // starts from a click on this exact message, so it should be ready to type
  // into without a second one.
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    fitToContent(node);
    node.focus();
    node.setSelectionRange(node.value.length, node.value.length);
  }, []);

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Escape') {
      event.preventDefault();
      onCancel();
      return;
    }
    // Enter sends, Shift+Enter breaks the line -- the composer's contract,
    // since this is the same act of sending a prompt.
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      if (changed) onSubmit(value);
    }
  }

  return (
    <div className={EDITOR_BUBBLE_CLASSES}>
      <textarea
        ref={ref}
        rows={1}
        aria-label="Edit prompt"
        className={EDITOR_TEXTAREA_CLASSES}
        value={value}
        onChange={event => {
          setValue(event.currentTarget.value);
          fitToContent(event.currentTarget);
        }}
        onKeyDown={handleKeyDown}
      />
      <div className={EDITOR_ACTIONS_CLASSES}>
        {/* Labelled past their visible text because a plan card's Cancel and
            the composer's Send sit on the same page. */}
        <button
          type="button"
          aria-label="Cancel edit"
          className={EDITOR_CANCEL_CLASSES}
          onClick={onCancel}
        >
          Cancel
        </button>
        <button
          type="button"
          aria-label="Send edited prompt"
          className={EDITOR_SEND_CLASSES}
          disabled={!changed}
          onClick={() => onSubmit(value)}
        >
          Send
        </button>
      </div>
    </div>
  );
}
