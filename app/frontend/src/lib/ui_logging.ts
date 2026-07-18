// Ships frontend failures into the persisted app-wide log so a UI crash
// is visible from the Logs panel, `cosci logs`, and /api/logs — the same
// places backend failures land — instead of only in a browser console
// nobody is watching.
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
