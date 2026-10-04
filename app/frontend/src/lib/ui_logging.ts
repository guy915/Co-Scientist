// Persist browser failures so diagnostics survive reloads.
import {postAppLogs, type ClientLogRecord} from '@/api/logs';

// Logging is best-effort: reporting an unavailable API must never break the
// page being diagnosed.
function postBestEffort(records: ClientLogRecord[]): void {
  void postAppLogs(records).catch(() => {
    // Reporting API failure must not itself break the page.
  });
}

export function logUiError(message: string, detail?: string): void {
  const full = detail ? `${message} | ${detail}` : message;
  postBestEffort([{message: full, level: 'error', logger: 'error'}]);
}

const INTERACTIVE_SELECTOR =
  'button, a, select, summary, [role="button"], ' +
  'input[type="button"], input[type="submit"]';

// Labels orient diagnostics, never capture a transcript; keep them well below
// the ingestion limit.
const LABEL_MAX_CHARS = 80;

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

// Batch interaction chatter to reduce writes; errors/navigation remain
// immediate.
const INTERACTION_FLUSH_MS = 2_000;

// Keep batches below the ingestion endpoint 50-record limit.
const INTERACTION_FLUSH_COUNT = 20;

let pendingInteractions: ClientLogRecord[] = [];
let interactionFlushTimer: number | null = null;

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

// Capture listeners observe controls before handlers stop propagation or React
// removes the target.
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
  window.addEventListener('pagehide', flushInteractions);
  return () => {
    document.removeEventListener('click', onClick, true);
    document.removeEventListener('submit', onSubmit, true);
    window.removeEventListener('pagehide', flushInteractions);
    flushInteractions();
  };
}

// ResizeObserver loop notices lack exception stacks and do not imply failed
// layout; suppress only these notices, never real callback exceptions.
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
