import {useEffect, useRef} from 'react';
import {getAppLogs, postAppLogs, type AppLogsPayload} from '@/api/logs';
import {useLocation} from 'react-router-dom';
import {DIAGNOSTIC_EVENT} from '@/shared/lib/dom_events';
import {
  EXPORT_LIMIT,
  browserExportContext,
  buildAppLogEntry,
  detailToClientRecord,
  formatDiagnosticExport,
  summarizeDiagnosticEntries,
  type DiagnosticLogEntry,
  type DiagnosticLogEventDetail,
  type PersistedAppLogs,
} from './layout_diagnostics_data';

// The feedback export is scoped to records after this anchor, so it must be
// taken when the shell mounts, not when feedback is first submitted.
function useSessionLogAnchor() {
  useEffect(() => {
    getAppLogs(sessionAfterId(), 1, 'WARNING')
      .then(ensureSessionBaseline)
      .catch(() => {
        // Without an anchor the export falls back to its first fetch.
      });
  }, []);
}

// Mounted for the shell lifetime; renders nothing.
export function SessionDiagnostics() {
  useSessionLogAnchor();
  useDiagnosticIngest();
  useNavigationLog();
  return null;
}

// sessionStorage preserves the log anchor across tab reloads but ends it on tab
// close; each tab owns its view.
const BASELINE_KEY = 'cosci-logs-session-baseline';

interface SessionBaseline {
  id: number;
}

// Private/full storage must not break diagnostics; degrade the anchor to
// memory.
let memoryBaseline: SessionBaseline | null = null;

function readBaseline(): SessionBaseline | null {
  try {
    const raw = window.sessionStorage.getItem(BASELINE_KEY);
    if (raw) return JSON.parse(raw) as SessionBaseline;
  } catch {
    // Unavailable storage falls back to the memory anchor.
  }
  return memoryBaseline;
}

function writeBaseline(baseline: SessionBaseline): void {
  memoryBaseline = baseline;
  try {
    window.sessionStorage.setItem(BASELINE_KEY, JSON.stringify(baseline));
  } catch {
    // The memory anchor already retains this load’s baseline.
  }
}

export function resetSessionBaselineForTest(): void {
  memoryBaseline = null;
  try {
    window.sessionStorage.removeItem(BASELINE_KEY);
  } catch {
    // The memory anchor was cleared even if storage is unavailable.
  }
}

export function sessionAfterId(): number {
  return readBaseline()?.id ?? 0;
}

// Feedback attaches this export of the current browsing session.
export async function sessionDiagnosticExport(): Promise<string> {
  let entries: DiagnosticLogEntry[] = [];
  let total = 0;
  try {
    const afterId = sessionAfterId();
    const payload = await getAppLogs(afterId, EXPORT_LIMIT);
    ensureSessionBaseline(payload);
    const loaded = buildLoadedLogs(payload, afterId);
    entries = loaded.entries;
    total = loaded.total;
  } catch {
    entries = [
      buildAppLogEntry(
        {
          id: 0,
          created_at: Date.now() / 1000,
          level: 'WARNING',
          levelno: 30,
          logger: 'ui.feedback',
          message:
            'Session diagnostics were unavailable when feedback was submitted.',
          run_id: null,
          exc_text: null,
        },
        1,
      ),
    ];
    total = 1;
  }
  const format = () =>
    formatDiagnosticExport({
      entries,
      total,
      counts: summarizeDiagnosticEntries(entries),
      context: browserExportContext(),
    });
  let report = format();
  while (report.length > 100_000 && entries.length) {
    entries.shift();
    report = format();
  }
  return report;
}

// Re-anchor if ids restart below the cursor. Capture before disposal guards so
// a discarded mount cannot make later loads hide session records.
function ensureSessionBaseline(payload: AppLogsPayload): void {
  const baseline = readBaseline();
  if (baseline === null || payload.last_id < baseline.id) {
    writeBaseline({id: payload.last_id});
  }
}

// Use server session_total: subtracting table totals breaks after retention
// prunes. Number the newest row by that uncapped total.
function buildLoadedLogs(
  payload: AppLogsPayload,
  requestAfterId: number,
): PersistedAppLogs {
  const baseline = readBaseline() ?? {id: payload.last_id};
  const session = payload.logs.filter(record => record.id > baseline.id);
  // Responses issued before the current anchor counted pre-session rows and
  // must contribute nothing.
  const total = requestAfterId < baseline.id ? 0 : payload.session_total;
  const shown = session.slice(-EXPORT_LIMIT);
  const first = total - shown.length + 1;
  return {
    entries: shown.map((record, index) =>
      buildAppLogEntry(record, first + index),
    ),
    total,
  };
}

// Ingest throughout the shell lifetime so no diagnostic event is lost.
export function useDiagnosticIngest() {
  useEffect(() => {
    function onDiagnosticEvent(event: Event) {
      const custom = event as CustomEvent<DiagnosticLogEventDetail>;
      if (!custom.detail?.stage) return;
      postAppLogs([detailToClientRecord(custom.detail)]).catch(() => {
        // Failed diagnostic ingestion must not break the page.
      });
    }
    window.addEventListener(DIAGNOSTIC_EVENT, onDiagnosticEvent);
    return () => {
      window.removeEventListener(DIAGNOSTIC_EVENT, onDiagnosticEvent);
    };
  }, []);
}

export function useNavigationLog() {
  const {pathname} = useLocation();
  const lastLogged = useRef<string | null>(null);

  useEffect(() => {
    if (lastLogged.current === pathname) return;
    const message =
      lastLogged.current === null
        ? `page loaded at ${pathname}`
        : `navigated to ${pathname}`;
    lastLogged.current = pathname;
    postAppLogs([{message, logger: 'navigation'}]).catch(() => {
      // Navigation logging must remain best-effort when the API is down.
    });
  }, [pathname]);
}
