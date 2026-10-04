import {useEffect, useRef, useState, type FormEvent} from 'react';
import {createPortal} from 'react-dom';
import {useLocation} from 'react-router-dom';
import {
  FEEDBACK_CATEGORIES,
  submitFeedback,
  type FeedbackCategory,
} from '@/api/feedback';
import {Icon} from '@/components/icon';
import {
  useBackgroundInert,
  useEscapeKey,
  useFocusTrap,
  useRestoreFocusOnClose,
} from '../hooks/dom';
import {sessionDiagnosticExport} from '../layout_diagnostics';
import {headerControlButtonClasses} from '../layout_primitives';

export function FeedbackControl({runId}: {runId?: string}) {
  const [open, setOpen] = useState(false);
  const {pathname} = useLocation();
  const currentRunId =
    runId ??
    (pathname.startsWith('/runs/') ? pathname.split('/')[2] : undefined);
  return (
    <>
      <button
        type="button"
        className={headerControlButtonClasses('ucs-feedback-control')}
        aria-label="Feedback"
        aria-haspopup="dialog"
        onClick={() => setOpen(true)}
      >
        <Icon aria-hidden="true" name="stars" />
        <span>Feedback</span>
      </button>
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
        <label>
          Category
          <select
            className="ucs-settings-field-input"
            value={category}
            onChange={event =>
              setCategory(event.target.value as FeedbackCategory)
            }
            disabled={busy}
          >
            {FEEDBACK_CATEGORIES.map(value => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
        <label>
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
            className="ucs-settings-field-input"
            onClick={onClose}
          >
            Cancel
          </button>
          <button
            type="submit"
            className="ucs-settings-field-input"
            disabled={busy || !message.trim()}
          >
            {busy ? 'Submitting…' : 'Submit'}
          </button>
        </div>
      </form>
    </div>
  );
}
