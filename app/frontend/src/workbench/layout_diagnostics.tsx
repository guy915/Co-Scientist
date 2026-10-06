import {useEffect, useId, useRef, useState} from 'react';
import {
  APP_LOGS_CHANGED_EVENT,
  getAppLogs,
  postAppLogs,
  type AppLogsPayload,
} from '@/api/logs';
import {Icon} from '@/components/icon';
import {copyText} from '@/lib/clipboard';
import {useLocation} from 'react-router-dom';
import {joinClasses, tooltipClassNames} from './classes';
import {DIAGNOSTIC_EVENT} from './dom_events';
import {useResetTimer} from './hooks/timers';
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
import {
  HEADER_CONTROL_ICON_CLASSES,
  headerControlButtonClasses,
} from './layout_primitives';

const LOGS_BUTTON_CLASSES = headerControlButtonClasses(
  'inline-flex px-[0.62rem] py-0 pl-[0.72rem]',
);

const STATUS_DOT_CLASSES = 'h-2 w-2 shrink-0 rounded-full';

const COPIED_RESET_MS = 2_000;

// Rescheduling replaces the prior expiry; cleanup prevents stale timers
// clearing a later copy label.
function useCopiedFlag() {
  const [copied, setCopied] = useState(false);
  const timer = useResetTimer();

  return {
    copied,
    markCopied() {
      setCopied(true);
      timer.schedule(() => setCopied(false), COPIED_RESET_MS);
    },
  };
}

// Refreshes on writes and tab focus, never on a timer, so an idle tab costs the
// database nothing.
function useWarningLogged(): boolean {
  const [logged, setLogged] = useState(false);

  useEffect(() => {
    let disposed = false;
    let latestRequest = 0;
    const load = () => {
      const request = ++latestRequest;
      const afterId = sessionAfterId();
      getAppLogs(afterId, 1, 'WARNING')
        .then(payload => {
          // Even a disposed mount must anchor the session before a later
          // response includes session-owned records.
          ensureSessionBaseline(payload);
          if (disposed || request !== latestRequest) return;
          setLogged(
            afterId >= (readBaseline()?.id ?? 0) && payload.session_total > 0,
          );
        })
        .catch(() => {
          if (disposed || request !== latestRequest) return;
          setLogged(false);
        });
    };
    const loadIfVisible = () => {
      if (!document.hidden) load();
    };
    load();
    document.addEventListener('visibilitychange', loadIfVisible);
    window.addEventListener(APP_LOGS_CHANGED_EVENT, load);
    return () => {
      disposed = true;
      document.removeEventListener('visibilitychange', loadIfVisible);
      window.removeEventListener(APP_LOGS_CHANGED_EVENT, load);
    };
  }, []);

  return logged;
}

export function DiagnosticsControl() {
  const copiedFlag = useCopiedFlag();
  const warningLogged = useWarningLogged();
  const statusId = useId();
  useDiagnosticIngest();
  useNavigationLog();

  async function onCopy() {
    await copyText(await sessionDiagnosticExport());
    copiedFlag.markCopied();
  }

  return (
    <button
      type="button"
      className={tooltipClassNames({
        className: LOGS_BUTTON_CLASSES,
        placement: 'bottom',
      })}
      aria-label="Logs — copy session logs"
      aria-describedby={statusId}
      data-tooltip="Copy session logs"
      onClick={() => void onCopy()}
    >
      <Icon
        aria-hidden="true"
        className={HEADER_CONTROL_ICON_CLASSES}
        name="content_copy"
      />
      <span>{copiedFlag.copied ? 'Copied' : 'Logs'}</span>
      <span
        aria-hidden="true"
        data-logged={warningLogged}
        className={joinClasses(
          STATUS_DOT_CLASSES,
          warningLogged
            ? 'bg-cosci-logs-danger-fg'
            : 'bg-cosci-logs-accent-fg opacity-40',
        )}
      />
      <span id={statusId} className="sr-only">
        {warningLogged
          ? 'A warning or error was logged this session'
          : 'No warnings or errors logged this session'}
      </span>
    </button>
  );
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

// The Logs button and feedback share the session anchor and exporter.
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
