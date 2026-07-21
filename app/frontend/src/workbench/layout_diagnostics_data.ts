import type {AppLogRecord, ClientLogRecord} from '@/api/logs';

export type DiagnosticLogLevel = 'info' | 'success' | 'error';

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
    level: detail.level === 'error' ? 'error' : 'info',
    logger: 'session',
    ...(detail.runId ? {run_id: detail.runId} : {}),
  };
}

// WARNING and above read as errors; DEBUG/INFO as info. Backend records
// have no "success" notion.
function appLogLevel(record: AppLogRecord): DiagnosticLogLevel {
  return record.levelno >= 30 ? 'error' : 'info';
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
    run: record.run_id ? `Run ${record.run_id.slice(0, 8)}` : 'Server',
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
  successCount: number;
  infoCount: number;
  runCount: number;
}

export function summarizeDiagnosticEntries(
  entries: DiagnosticLogEntry[],
): DiagnosticCounts {
  return {
    errorCount: entries.filter(entry => entry.level === 'error').length,
    successCount: entries.filter(entry => entry.level === 'success').length,
    infoCount: entries.filter(entry => entry.level === 'info').length,
    runCount: new Set(entries.map(({run}) => run).filter(Boolean)).size,
  };
}
