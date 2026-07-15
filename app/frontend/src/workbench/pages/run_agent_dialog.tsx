import {type FormEvent, useState} from 'react';
import {askRunQuestion, sendRunSteering} from '@/api/runs';

/** Grounded follow-up dialog shared by report- and idea-level Agent actions. */
export function RunAgentDialog({
  runId,
  initialQuestion,
  steering,
  onClose,
}: {
  runId: string;
  initialQuestion?: string;
  steering?: boolean;
  onClose: () => void;
}) {
  const [question, setQuestion] = useState(initialQuestion || '');
  const [answer, setAnswer] = useState('');
  const [error, setError] = useState('');
  const [asking, setAsking] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const text = question.trim();
    if (!text) return;
    setAsking(true);
    setError('');
    try {
      if (steering) {
        await sendRunSteering(runId, text);
        setAnswer(
          'Guidance queued. The Supervisor will incorporate it at the next safe task boundary.',
        );
        setQuestion('');
      } else {
        setAnswer(await askRunQuestion(runId, text));
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Agent unavailable');
    } finally {
      setAsking(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-black/50 p-4"
      role="presentation"
      onMouseDown={event => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="agent-dialog-title"
        className="grid max-h-[min(42rem,90vh)] w-[min(42rem,100%)] gap-4 overflow-auto rounded-xl bg-cosci-bg p-6 text-cosci-fg"
      >
        <div className="flex items-center justify-between gap-4">
          <h2 id="agent-dialog-title" className="text-xl font-medium">
            Open Agent
          </h2>
          <button
            type="button"
            className="rounded-full border border-cosci-border px-3 py-2 text-sm hover:bg-cosci-hover"
            onClick={onClose}
            aria-label="Close Agent"
          >
            Close
          </button>
        </div>
        <form className="grid gap-3" onSubmit={event => void submit(event)}>
          <label className="grid gap-2">
            <span>
              {steering
                ? 'Guide this active research run'
                : 'Ask about this Goal Report'}
            </span>
            <textarea
              className="min-h-28 rounded-xl border border-cosci-border bg-transparent p-3"
              value={question}
              onChange={event => setQuestion(event.currentTarget.value)}
            />
          </label>
          <button
            type="submit"
            disabled={asking || !question.trim()}
            className="w-fit rounded-full bg-cosci-blue-strong px-5 py-2 text-white disabled:opacity-50"
          >
            {asking
              ? steering
                ? 'Sending…'
                : 'Asking…'
              : steering
                ? 'Send guidance'
                : 'Ask Agent'}
          </button>
        </form>
        {error ? <p role="alert">{error}</p> : null}
        {asking && !steering ? (
          <section
            aria-label="Agent answer"
            className="text-cosci-muted"
            role="status"
            aria-live="polite"
          >
            <span className="animate-pulse">Thinking…</span>
          </section>
        ) : answer ? (
          <section aria-label="Agent answer" className="whitespace-pre-wrap">
            {answer}
          </section>
        ) : null}
      </section>
    </div>
  );
}
