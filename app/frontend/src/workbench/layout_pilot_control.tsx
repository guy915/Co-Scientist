import {useState, type ReactNode} from 'react';
import {submitFeedback, type FeedbackCategory} from '@/api/feedback';
import {Icon} from '@/components/icon';
import {useAudience} from './audience_context';
import {FEEDBACK_CATEGORIES, PILOT_FEEDBACK} from './audience_content';
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
  '!w-[min(24rem,calc(100vw-2rem))] !p-0';

// Submission lifecycle. 'sent' latches until the panel is reopened, so the
// tester gets an explicit confirmation rather than a silently cleared box.
type SendState = 'idle' | 'sending' | 'sent' | 'error';

// Owns the draft note and its submission. Extracted from the panel below so
// the rendering stays a plain function of this state.
function useFeedbackForm() {
  const {audience} = useAudience();
  const [category, setCategory] = useState<FeedbackCategory>('bug');
  const [message, setMessage] = useState('');
  const [state, setState] = useState<SendState>('idle');

  async function send() {
    if (!message.trim()) return;
    setState('sending');
    try {
      await submitFeedback({message: message.trim(), category, audience});
      setMessage('');
      setState('sent');
    } catch {
      setState('error');
    }
  }

  return {
    category,
    setCategory,
    message,
    // Editing after a failed or completed send returns the form to idle, so
    // the previous outcome does not linger over a fresh note.
    setMessage: (value: string) => {
      setMessage(value);
      if (state === 'sent' || state === 'error') setState('idle');
    },
    state,
    send,
  };
}

// Category chips; the selected one carries the same filled tint the rest of
// the shell uses for selection.
function CategoryChips({
  category,
  onSelect,
}: {
  category: FeedbackCategory;
  onSelect: (value: FeedbackCategory) => void;
}) {
  return (
    <div
      className="ucs-feedback-chips"
      role="radiogroup"
      aria-label="Feedback category"
    >
      {FEEDBACK_CATEGORIES.map(option => (
        <button
          key={option.value}
          type="button"
          role="radio"
          aria-checked={category === option.value}
          className={
            category === option.value
              ? 'ucs-feedback-chip ucs-feedback-chip--selected'
              : 'ucs-feedback-chip'
          }
          onClick={() => onSelect(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

/**
 * Header control replacing Logs for SBI/UCD: a short feedback form posting to
 * the pilot feedback endpoint.
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
  const form = useFeedbackForm();
  const sending = form.state === 'sending';

  return (
    <>
      <button
        type="button"
        className={tooltipClassNames({
          className: BUTTON_CLASSES,
          placement: 'left',
        })}
        data-tooltip="Send feedback"
        aria-expanded={open}
        onClick={onToggle}
      >
        <Icon aria-hidden="true" className="text-[1.05rem]" name="stars" />
        <span>Feedback</span>
      </button>
      {open &&
        renderPopover(
          <form
            className="ucs-feedback-form"
            onSubmit={event => {
              event.preventDefault();
              void form.send();
            }}
          >
            <h2 className="ucs-feedback-title">{PILOT_FEEDBACK.title}</h2>
            <p className="ucs-feedback-intro">{PILOT_FEEDBACK.intro}</p>
            <CategoryChips
              category={form.category}
              onSelect={form.setCategory}
            />
            <label className="sr-only" htmlFor="cosci-feedback-message">
              {PILOT_FEEDBACK.placeholder}
            </label>
            <textarea
              id="cosci-feedback-message"
              className="ucs-feedback-input"
              rows={4}
              placeholder={PILOT_FEEDBACK.placeholder}
              value={form.message}
              disabled={sending}
              onChange={event => form.setMessage(event.target.value)}
            />
            <div className="ucs-feedback-actions">
              <button
                type="submit"
                className="ucs-panel-button"
                disabled={sending || !form.message.trim()}
              >
                {sending ? PILOT_FEEDBACK.sending : PILOT_FEEDBACK.submit}
              </button>
              {/* Outcome and the button share a row: the message sits inline
                  rather than shifting the form's height when it appears. */}
              <span aria-live="polite" className="ucs-feedback-status">
                {form.state === 'sent' && PILOT_FEEDBACK.thanks}
                {form.state === 'error' && PILOT_FEEDBACK.error}
              </span>
            </div>
          </form>,
          POPOVER_CLASSES,
        )}
    </>
  );
}
