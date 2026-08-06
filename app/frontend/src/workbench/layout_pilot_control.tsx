import {useState} from 'react';
import {submitFeedback, type FeedbackCategory} from '@/api/feedback';
import {useAudience} from './audience_context';
import {FEEDBACK_CATEGORIES, PILOT_FEEDBACK} from './audience_content';
import {
  HeaderControlTrigger,
  headerControlPopoverClasses,
  type HeaderControlProps,
} from './layout_primitives';

const POPOVER_CLASSES = headerControlPopoverClasses(
  '!w-[min(24rem,calc(100vw-2rem))]',
);

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

// The return type of useFeedbackForm, forwarded as-is to the popover body.
type FeedbackFormState = ReturnType<typeof useFeedbackForm>;

// The message textarea, with its screen-reader label.
function FeedbackMessageField({
  message,
  sending,
  onChange,
}: {
  message: string;
  sending: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <>
      <label className="sr-only" htmlFor="cosci-feedback-message">
        {PILOT_FEEDBACK.placeholder}
      </label>
      <textarea
        id="cosci-feedback-message"
        className="ucs-feedback-input"
        rows={4}
        placeholder={PILOT_FEEDBACK.placeholder}
        value={message}
        disabled={sending}
        onChange={event => onChange(event.target.value)}
      />
    </>
  );
}

// The submit button plus the inline sent/error outcome message.
function FeedbackActions({
  sending,
  disabled,
  state,
}: {
  sending: boolean;
  disabled: boolean;
  state: SendState;
}) {
  return (
    <div className="ucs-feedback-actions">
      <button type="submit" className="ucs-panel-button" disabled={disabled}>
        {sending ? PILOT_FEEDBACK.sending : PILOT_FEEDBACK.submit}
      </button>
      {/* Outcome and the button share a row: the message sits inline
          rather than shifting the form's height when it appears. */}
      <span aria-live="polite" className="ucs-feedback-status">
        {state === 'sent' && PILOT_FEEDBACK.thanks}
        {state === 'error' && PILOT_FEEDBACK.error}
      </span>
    </div>
  );
}

// The popover body: category chips, message field, and submit action. All
// state lives in useFeedbackForm; this only renders what it is handed.
function FeedbackForm({
  form,
  sending,
}: {
  form: FeedbackFormState;
  sending: boolean;
}) {
  return (
    <form
      className="ucs-feedback-form"
      onSubmit={event => {
        event.preventDefault();
        void form.send();
      }}
    >
      <h2 className="ucs-feedback-title">{PILOT_FEEDBACK.title}</h2>
      <p className="ucs-feedback-intro">{PILOT_FEEDBACK.intro}</p>
      <p className="ucs-feedback-intro text-xs text-cosci-muted">
        {PILOT_FEEDBACK.privacyNote}
      </p>
      <CategoryChips category={form.category} onSelect={form.setCategory} />
      <FeedbackMessageField
        message={form.message}
        sending={sending}
        onChange={form.setMessage}
      />
      <FeedbackActions
        sending={sending}
        disabled={sending || !form.message.trim()}
        state={form.state}
      />
    </form>
  );
}

/**
 * Header control replacing Logs for SBI/UCD: a short feedback form posting to
 * the pilot feedback endpoint.
 */
export function PilotControl({
  open,
  onToggle,
  renderPopover,
}: HeaderControlProps) {
  const form = useFeedbackForm();
  const sending = form.state === 'sending';

  return (
    <>
      <HeaderControlTrigger
        icon="stars"
        label="Feedback"
        tooltip="Send feedback"
        open={open}
        onToggle={onToggle}
      />
      {open &&
        renderPopover(
          <FeedbackForm form={form} sending={sending} />,
          POPOVER_CLASSES,
        )}
    </>
  );
}
