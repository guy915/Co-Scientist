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
import {
  joinClasses,
  SETTINGS_DIALOG_CLASSES,
  SETTINGS_DIALOG_TITLE_CLASSES,
  SETTINGS_FIELD_CLASSES,
  SETTINGS_FIELD_LABEL_CLASSES,
  SETTINGS_SCRIM_CLASSES,
} from '../classes';
import {Button} from '@/shared/ui';

import {sessionDiagnosticExport} from '../layout_diagnostics';
import {SettingsSelect} from './settings_dialog';

export function FeedbackControl({runId}: {runId?: string}) {
  const [open, setOpen] = useState(false);
  const {pathname} = useLocation();
  const currentRunId =
    runId ??
    (pathname.startsWith('/runs/') ? pathname.split('/')[2] : undefined);
  return (
    <>
      <Button
        variant="tonal"
        size="sm"
        icon="stars"
        tooltip="Send feedback"
        tooltipPlacement="bottom"
        aria-label="Feedback"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen(current => !current)}
      >
        <span>Feedback</span>
      </Button>
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
        className={SETTINGS_SCRIM_CLASSES}
        aria-hidden="true"
        onClick={onClose}
      />
      <form
        className={joinClasses(
          SETTINGS_DIALOG_CLASSES,
          'h-auto max-h-[calc(100dvh-2rem)] w-[min(32rem,calc(100vw-2rem))] gap-5 overflow-y-auto p-6',
        )}
        role="dialog"
        aria-modal="true"
        aria-label="Feedback"
        onSubmit={event => void submit(event)}
      >
        <h2 className={SETTINGS_DIALOG_TITLE_CLASSES}>Feedback</h2>
        <div>
          <label
            id="feedback-category-label"
            className={joinClasses('grid gap-2', SETTINGS_FIELD_LABEL_CLASSES)}
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
        <label
          className={joinClasses('grid gap-2', SETTINGS_FIELD_LABEL_CLASSES)}
        >
          Message
          <textarea
            ref={messageRef}
            // The important size outranks the unlayered coarse-pointer font
            // floor, as the field class did before it moved to utilities.
            className={joinClasses(
              SETTINGS_FIELD_CLASSES,
              'min-h-32 resize-y !text-[0.9rem]',
            )}
            rows={6}
            maxLength={8000}
            value={message}
            onChange={event => setMessage(event.target.value)}
            required
            disabled={busy}
          />
        </label>
        {error && <p role="alert">{error}</p>}
        <div className="flex gap-3 [justify-content:end]">
          <Button variant="outlined" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={busy || !message.trim()}>
            {busy ? 'Submitting…' : 'Submit'}
          </Button>
        </div>
      </form>
    </div>
  );
}
