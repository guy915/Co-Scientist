import type {AppLogRecord, ClientLogRecord} from '@/api/logs';

export type DiagnosticLogLevel = 'info' | 'warning' | 'error';

// One rendered row in the Logs panel. Every entry comes from the single
// persisted app-wide log (the backend's app_logs table): backend records
// are captured server-side, and in-page diagnostic events are POSTed to
// the same log before being re-fetched. That keeps the panel identical on
// every route, numbered by the store's consecutive row ids.
export interface DiagnosticLogEntry {
  /** Real store row id: stable, but gapped once noise is filtered. */
  id: number;
  /**
   * Position in the filtered stream, rendered as "#N". Store ids are
   * assigned globally (hidden noise consumes them), so showing them
   * raw makes a filtered list look like rows failed to render.
   */
  number: number;
  time: string;
  run: string;
  stage: string;
  level: DiagnosticLogLevel;
  /** Level name (INFO, ERROR, ...) shown in the meta row. */
  levelName: string;
  /** The log message, rendered as plain text. */
  message: string;
  /** Formatted traceback, appended below the message when present. */
  excText: string | null;
  /** Structured form kept for the Copy action (machine-readable). */
  payload: Record<string, unknown>;
}

// Server-owned records appear alongside run records, but they must not make
// the summary's Runs chip imply that a research run produced the record.
export const SERVER_LOG_SOURCE = 'Server';

// How many of the newest entries the Copy action serializes.
export const COPY_LIMIT = 50;

// How many of the newest records the panel fetches and shows.
export const PANEL_LIMIT = 100;

// How often the persisted backend log is re-fetched in the background.
export const APP_LOGS_POLL_MS = 5_000;

// Shape of the `cosci-diagnostic-event` CustomEvent's `detail`, as dispatched
// by callers elsewhere in the app (e.g. useChatSession's emitDiagnosticEvent)
// to surface a diagnostic line without those callers depending on the
// DiagnosticsControl component directly.
export interface DiagnosticLogEventDetail {
  /**
   * Real run id, when the event belongs to a run. Never a title: this
   * lands in the persisted record's `run_id`, which is served over the
   * API, so goal-derived text here would publish research content.
   */
  runId?: string;
  stage: string;
  level?: DiagnosticLogLevel;
  payload?: Record<string, unknown>;
}

// The fetched window plus the size of the whole filtered stream. The
// newest shown record is numbered `total`, so the badge and the top row
// carry the same number however much noise is hidden behind them.
export interface PersistedAppLogs {
  entries: DiagnosticLogEntry[];
  total: number;
}

const DIAGNOSTIC_TIME_FMT = new Intl.DateTimeFormat(undefined, {
  hour: 'numeric',
  minute: '2-digit',
  second: '2-digit',
});

function formatDiagnosticTime(date = new Date()): string {
  return DIAGNOSTIC_TIME_FMT.format(date);
}

// The event detail arrives from an untyped CustomEvent, so an
// unrecognized level is treated as info rather than forwarded to the
// ingestion endpoint (which would map it to info anyway, silently).
function clientLevel(level: DiagnosticLogLevel | undefined): string {
  return level === 'error' || level === 'warning' ? level : 'info';
}

// Converts a raw diagnostic-event detail into the record shape the
// ingestion endpoint accepts. The payload rides inside the message so the
// persisted line stays greppable from the CLI too.
export function detailToClientRecord(
  detail: DiagnosticLogEventDetail,
): ClientLogRecord {
  const payload = detail.payload || {};
  const suffix = Object.keys(payload).length
    ? ` ${JSON.stringify(payload)}`
    : '';
  return {
    message: `${detail.stage}${suffix}`,
    level: clientLevel(detail.level),
    logger: 'session',
    ...(detail.runId ? {run_id: detail.runId} : {}),
  };
}

// The three bands the chips tally, keyed off Python's numeric levels:
// ERROR and CRITICAL (40+) are errors, WARNING (30) stands on its own,
// DEBUG/INFO below it are info. The split matches the level name each row
// already prints, so a chip and the rows behind it always agree.
function appLogLevel(record: AppLogRecord): DiagnosticLogLevel {
  if (record.levelno >= 40) return 'error';
  return record.levelno >= 30 ? 'warning' : 'info';
}

// Maps one persisted app_logs record into a rendered log entry. Records
// with no run id are attributed to the server itself.
export function buildAppLogEntry(
  record: AppLogRecord,
  number: number,
): DiagnosticLogEntry {
  return {
    id: record.id,
    number,
    time: formatDiagnosticTime(new Date(record.created_at * 1000)),
    run: record.run_id ? `Run ${record.run_id.slice(0, 8)}` : SERVER_LOG_SOURCE,
    stage: record.logger,
    level: appLogLevel(record),
    levelName: record.level,
    message: record.message,
    excText: record.exc_text,
    payload: {
      level: record.level,
      message: record.message,
      ...(record.exc_text ? {exc_text: record.exc_text} : {}),
    },
  };
}

// Per-level entry tallies plus the number of distinct runs represented, for
// the summary chips in DiagnosticLogsPanel.
export interface DiagnosticCounts {
  errorCount: number;
  warningCount: number;
  infoCount: number;
  runCount: number;
}

export function summarizeDiagnosticEntries(
  entries: DiagnosticLogEntry[],
): DiagnosticCounts {
  return {
    errorCount: entries.filter(entry => entry.level === 'error').length,
    warningCount: entries.filter(entry => entry.level === 'warning').length,
    infoCount: entries.filter(entry => entry.level === 'info').length,
    // Only run-owned records contribute here. Server records remain visible
    // and explicitly labelled in the list, rather than masquerading as runs.
    runCount: new Set(
      entries.map(({run}) => run).filter(run => run !== SERVER_LOG_SOURCE),
    ).size,
  };
}
