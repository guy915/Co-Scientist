// Ships frontend failures and user interactions into the persisted
// app-wide log so a UI crash or a button press is visible from the Logs
// panel, `cosci logs`, and /api/logs — the same places backend records
// land — instead of only in a browser console nobody is watching.
import {postAppLogs} from '@/api/logs';

/**
 * Persists one UI error line. Best-effort: a failed POST is swallowed so
 * error reporting can never itself break the page.
 *
 * @param message The error summary.
 * @param detail Optional extra context (e.g. a component stack).
 */
export function logUiError(message: string, detail?: string): void {
  const full = detail ? `${message} | ${detail}` : message;
  void postAppLogs([{message: full, level: 'error', logger: 'error'}]).catch(
    () => {
      // Offline or API down: nothing useful left to do.
    },
  );
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

// Best-effort persistence shared by the interaction listeners.
function logUiInteraction(message: string): void {
  void postAppLogs([{message, logger: 'interaction'}]).catch(() => {
    // Offline or API down: interaction logging is best-effort.
  });
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
  return () => {
    document.removeEventListener('click', onClick, true);
    document.removeEventListener('submit', onSubmit, true);
  };
}

/**
 * Subscribes to uncaught errors and unhandled promise rejections and
 * persists them.
 *
 * @returns A function that removes the listeners again.
 */
export function installUiErrorLogging(): () => void {
  function onError(event: ErrorEvent) {
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
