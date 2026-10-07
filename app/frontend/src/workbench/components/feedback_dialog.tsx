import {useEffect, useRef, useState, type FormEvent} from 'react';
import {createPortal} from 'react-dom';
import {useLocation} from 'react-router-dom';
import {
  FEEDBACK_CATEGORIES,
  submitFeedback,
  type FeedbackCategory,
} from '@/api/feedback';
import {
  useBackgroundInert,
  useEscapeKey,
  useFocusTrap,
  useRestoreFocusOnClose,
} from '../hooks/dom';
import {joinClasses, SETUP_PRIMARY_BUTTON_CLASSES} from '../classes';

import {sessionDiagnosticExport} from '../layout_diagnostics';
import {HeaderControlTrigger} from '../layout_primitives';
import {SettingsSelect} from './settings_dialog';

// The dialog surface shares the page hover tone, so actions need the menu-row
// tone and the filled button needs elevation to show hover.
const SUBMIT_CLASSES = joinClasses(
  SETUP_PRIMARY_BUTTON_CLASSES,
  'transition-shadow enabled:hover:shadow-md',
);

export function FeedbackControl({runId}: {runId?: string}) {
  const [open, setOpen] = useState(false);
  const {pathname} = useLocation();
  const currentRunId =
    runId ??
    (pathname.startsWith('/runs/') ? pathname.split('/')[2] : undefined);
  return (
    <>
      <HeaderControlTrigger
        icon="stars"
        label="Feedback"
        tooltip="Send feedback"
        open={open}
        onToggle={() => setOpen(current => !current)}
        ariaLabel="Feedback"
        ariaHasPopup="dialog"
      />
      {open &&
        createPortal(
          <FeedbackDialog
            runId={currentRunId}
            onClose={() => setOpen(false)}
          />,
          document.body,
        )}
    </>
  );
}

export function FeedbackDialog({
  runId,
  onClose,
}: {
  runId?: string;
  onClose: () => void;
}) {
  const root = useRef<HTMLDivElement>(null);
  const messageRef = useRef<HTMLTextAreaElement>(null);
  const mounted = useRef(true);
  const [category, setCategory] = useState<FeedbackCategory>('Bug');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useRestoreFocusOnClose();
  useFocusTrap(root);
  useBackgroundInert(root);
  useEscapeKey(onClose, true);
  useEffect(() => {
    mounted.current = true;
    messageRef.current?.focus();
    return () => {
      mounted.current = false;
    };
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || !message.trim()) return;
    setBusy(true);
    setError('');
    try {
      const diagnostics = await sessionDiagnosticExport();
      if (!mounted.current) return;
      await submitFeedback({
        category,
        message: message.trim(),
        diagnostics,
        url: window.location.href.slice(0, 2048),
        ...(runId ? {run_id: runId} : {}),
      });
      if (mounted.current) onClose();
    } catch {
      if (mounted.current) {
        setError(
          'Feedback could not be sent. Please wait a minute and try again.',
        );
        setBusy(false);
      }
    }
  }

  return (
    <div className="ucs-settings-dialog-root" ref={root}>
      <div
        className="ucs-settings-dialog-scrim"
        aria-hidden="true"
        onClick={onClose}
      />
      <form
        className="ucs-settings-dialog ucs-feedback-dialog"
        role="dialog"
        aria-modal="true"
        aria-label="Feedback"
        onSubmit={event => void submit(event)}
      >
        <h2 className="ucs-settings-dialog-title">Feedback</h2>
        <div>
          <label
            id="feedback-category-label"
            className="ucs-settings-field-label"
            htmlFor="feedback-category"
          >
            Category
          </label>
          <SettingsSelect
            value={category}
            options={FEEDBACK_CATEGORIES}
            optionLabel={option => option}
            name="Category"
            triggerId="feedback-category"
            labelId="feedback-category-label"
            disabled={busy}
            onChange={setCategory}
          />
        </div>
        <label className="ucs-settings-field-label">
          Message
          <textarea
            ref={messageRef}
            className="ucs-settings-field-input"
            rows={6}
            maxLength={8000}
            value={message}
            onChange={event => setMessage(event.target.value)}
            required
            disabled={busy}
          />
        </label>
        {error && <p role="alert">{error}</p>}
        <div className="ucs-feedback-actions">
          <button
            type="button"
            className="min-h-[2.6rem] cursor-pointer rounded-full border border-cosci-btn-secondary-border bg-transparent px-[1.45rem] font-medium text-cosci-btn-secondary-fg hover:bg-cosci-menu-row-hover focus-visible:bg-cosci-menu-row-hover"
            onClick={onClose}
          >
            Cancel
          </button>
          <button
            type="submit"
            className={SUBMIT_CLASSES}
            disabled={busy || !message.trim()}
          >
            {busy ? 'Submitting…' : 'Submit'}
          </button>
        </div>
      </form>
    </div>
  );
}
