// Ships frontend failures and user interactions into the persisted
// app-wide log so a UI crash or a button press is visible from the Logs
// panel, `cosci logs`, and /api/logs — the same places backend records
// land — instead of only in a browser console nobody is watching.
import {postAppLogs, type ClientLogRecord} from '@/api/logs';

// Ships records and swallows any failure. Every write from this module is
// best-effort on purpose: offline or with the API down there is nothing
// useful left to do, and reporting an error or a click must never itself
// break the page it is reporting on.
function postBestEffort(records: ClientLogRecord[]): void {
  void postAppLogs(records).catch(() => {
    // Deliberately ignored; see above.
  });
}

/**
 * Persists one UI error line. Best-effort: a failed POST is swallowed so
 * error reporting can never itself break the page.
 *
 * @param message The error summary.
 * @param detail Optional extra context (e.g. a component stack).
 */
export function logUiError(message: string, detail?: string): void {
  const full = detail ? `${message} | ${detail}` : message;
  postBestEffort([{message: full, level: 'error', logger: 'error'}]);
}

// Elements whose clicks are worth a log line: actual controls, not
// arbitrary text. Clicks elsewhere are ignored.
const INTERACTIVE_SELECTOR =
  'button, a, select, summary, [role="button"], ' +
  'input[type="button"], input[type="submit"]';

// Labels are for orientation, not transcripts: cap them well below the
// server-side message limit.
const LABEL_MAX_CHARS = 80;

// Human-readable label for a control: aria-label beats visible text
// (icon-only buttons), whitespace is collapsed, and long labels are
// truncated with an ellipsis.
function interactionLabel(control: Element): string {
  const raw =
    control.getAttribute('aria-label') ||
    control.textContent ||
    control.getAttribute('title') ||
    '';
  const label = raw.replace(/\s+/g, ' ').trim();
  return label.length > LABEL_MAX_CHARS
    ? `${label.slice(0, LABEL_MAX_CHARS)}…`
    : label;
}

// Interaction records are orientation chatter, not emergencies: they
// buffer briefly and ship as one batched POST instead of one request per
// click. Errors and navigation keep their immediacy.
const INTERACTION_FLUSH_MS = 2_000;

// Buffer size that flushes immediately, keeping every batch comfortably
// under the ingestion endpoint's 50-record cap.
const INTERACTION_FLUSH_COUNT = 20;

let pendingInteractions: ClientLogRecord[] = [];
let interactionFlushTimer: number | null = null;

// Posts the buffered interaction records as one batch.
function flushInteractions(): void {
  if (interactionFlushTimer !== null) {
    window.clearTimeout(interactionFlushTimer);
    interactionFlushTimer = null;
  }
  if (!pendingInteractions.length) return;
  const batch = pendingInteractions;
  pendingInteractions = [];
  postBestEffort(batch);
}

// Buffers one interaction record; the buffer ships on a short timer,
// when it fills, and when the page hides or the listeners uninstall.
function logUiInteraction(message: string): void {
  pendingInteractions.push({message, logger: 'interaction'});
  if (pendingInteractions.length >= INTERACTION_FLUSH_COUNT) {
    flushInteractions();
    return;
  }
  if (interactionFlushTimer === null) {
    interactionFlushTimer = window.setTimeout(
      flushInteractions,
      INTERACTION_FLUSH_MS,
    );
  }
}

/**
 * Subscribes to user interactions — clicks on interactive elements and
 * form submissions — and persists them as `ui.interaction` records.
 *
 * Listeners run in the capture phase on `document`, so interactions are
 * recorded even when a handler stops propagation or React re-renders the
 * target away.
 *
 * @returns A function that removes the listeners again.
 */
export function installUiInteractionLogging(): () => void {
  function onClick(event: Event) {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const control = target.closest(INTERACTIVE_SELECTOR);
    if (!control) return;
    const tag = control.tagName.toLowerCase();
    logUiInteraction(`click: "${interactionLabel(control)}" (${tag})`);
  }

  function onSubmit(event: Event) {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    const label =
      form.getAttribute('aria-label') || form.getAttribute('name') || form.id;
    logUiInteraction(`submit: "${label || 'form'}" (form)`);
  }

  document.addEventListener('click', onClick, true);
  document.addEventListener('submit', onSubmit, true);
  // The page going away is the last chance to ship whatever is buffered.
  window.addEventListener('pagehide', flushInteractions);
  return () => {
    document.removeEventListener('click', onClick, true);
    document.removeEventListener('submit', onSubmit, true);
    window.removeEventListener('pagehide', flushInteractions);
    flushInteractions();
  };
}

/**
 * Subscribes to uncaught errors and unhandled promise rejections and
 * persists them.
 *
 * @returns A function that removes the listeners again.
 */
// Browser notices that arrive as window "error" events without anything
// having failed. A ResizeObserver whose callback changes layout makes the
// browser announce an undelivered-notification loop this way: it carries
// no error object, no file and no line, and the layout still settles.
// Persisting them costs an ERROR row each — they arrive many per second,
// and the panel shows a fixed newest-100 window, so a burst evicts the
// records someone opened the panel to read. A callback that genuinely
// throws still surfaces: that arrives as its own exception with a stack,
// which this pattern does not match.
const BENIGN_ERROR_PATTERN = /^(Uncaught )?ResizeObserver loop /;

export function installUiErrorLogging(): () => void {
  function onError(event: ErrorEvent) {
    if (BENIGN_ERROR_PATTERN.test(event.message)) return;
    const where = event.filename
      ? ` (${event.filename}:${event.lineno ?? 0})`
      : '';
    logUiError(`uncaught error: ${event.message}${where}`);
  }

  function onRejection(event: Event) {
    const {reason} = event as Event & {reason?: unknown};
    logUiError(`unhandled rejection: ${String(reason)}`);
  }

  window.addEventListener('error', onError);
  window.addEventListener('unhandledrejection', onRejection);
  return () => {
    window.removeEventListener('error', onError);
    window.removeEventListener('unhandledrejection', onRejection);
  };
}
