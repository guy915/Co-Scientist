import {
  type AppLogRecord,
  type ClientLogRecord,
  reportAppLogs,
} from '@/api/logs';
import {useState} from 'react';
import {useResetTimer} from './hooks/timers';

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

// How many of the newest entries the Copy action serializes. Matching
// PANEL_LIMIT means an export carries the whole window the reader was
// looking at: a copy that stopped short of it cut the run's narrative in
// half, since one run's stage records alone can fill most of the window.
export const COPY_LIMIT = 100;

// How many of the newest records the panel fetches and shows.
export const PANEL_LIMIT = 100;

// How often the persisted backend log is re-fetched in the background,
// by whether the panel is open. An open panel is a live view someone is
// watching, so it ticks fast enough to read as real time; a closed one
// only feeds the badge, where a slower tick keeps the steady-state query
// load off the database whose single writer every run competes for.
export const APP_LOGS_POLL_MS = {open: 2_000, closed: 5_000};

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

// Serializes the Logs panel's entries for the Copy action.
//
// A bare JSON array is machine-readable but says nothing about what the
// log is, what it deliberately omits, or how its two id columns differ —
// context a maintainer (or a coding agent) reading a pasted export has no
// other way to recover. The export is therefore a human-readable preamble
// followed by the same JSON entries under a marker line, so it stays
// pasteable into an issue and sliceable back into data.

// Separates the preamble from the machine-readable entry array. Exported
// so readers (and tests) can slice the JSON back out by a stable string.
export const EXPORT_LOGS_MARKER = '=== LOGS (JSON) ===';

// Page context worth carrying with an export. Injected rather than read
// from `window` here so the formatter stays pure.
export interface DiagnosticExportContext {
  currentUrl?: string;
  userAgent?: string;
  exportedAt?: Date;
}

// Everything the preamble reports on, bundled so the entry point stays
// under the shared argument ceiling.
export interface DiagnosticExport {
  entries: DiagnosticLogEntry[];
  /** Records added this browsing session; the panel's Total chip. */
  total: number;
  counts: DiagnosticCounts;
  context?: DiagnosticExportContext;
}

const UNAVAILABLE = 'Unavailable';

// What the log is and where it comes from.
function aboutSection(): string[] {
  return [
    '=== ABOUT THESE DIAGNOSTIC LOGS ===',
    'Co-Scientist workbench diagnostic export. The Logs panel renders one',
    'durable, app-wide log: backend records from the API, the durable task',
    'workers and the co_scientist engine, one compact stage record per run',
    'event, and frontend records this browser posted. It is scoped to this',
    'browsing session (records that predate it are excluded; a tab reload',
    'keeps the session, closing the tab ends it) and to what this caller',
    'may see. Share the whole export when reporting a',
    'problem — the preamble below is the context a reader would otherwise',
    'have to guess at.',
    '',
  ];
}

// What does and does not reach the log, so an absence can be read as
// "filtered" rather than "never happened".
function tracksSection(): string[] {
  return [
    '=== WHAT THIS TRACKS ===',
    'Run stages:',
    '- lifecycle, safety.intake, supervisor.plan, literature_review,',
    '  generate, reflection, proximity, ranking, evolve, meta_review,',
    '  deep_verification, citation_audit, research_overview, report, status',
    'Backend:',
    '- app, worker and store records, plus engine records at INFO and above',
    'Frontend (ui.*):',
    '- page loads and route changes, uncaught errors, unhandled rejections,',
    '  React render errors, and control interactions',
    'Deliberately absent:',
    '- per-call HTTP/LLM chatter below WARNING, which is never persisted',
    '- access, interaction and navigation noise, hidden from the default',
    '  view but present in `cosci logs --all`',
    '- verbatim repeats of a record within a 10-minute window',
    '',
  ];
}

// The context fields with their fallbacks resolved.
function resolveContext(context: DiagnosticExportContext) {
  return {
    exportedAt: (context.exportedAt ?? new Date()).toLocaleString(),
    currentUrl: context.currentUrl ?? UNAVAILABLE,
    userAgent: context.userAgent ?? UNAVAILABLE,
  };
}

// Where and when this export was taken.
function sessionSection(
  {entries, total}: DiagnosticExport,
  exported: DiagnosticLogEntry[],
  context: DiagnosticExportContext,
): string[] {
  const oldest = exported[0];
  const first = oldest ? `#${oldest.number} at ${oldest.time}` : 'none';
  const {exportedAt, currentUrl, userAgent} = resolveContext(context);
  return [
    '=== SESSION DETAILS ===',
    `Exported: ${exportedAt}`,
    `Current URL: ${currentUrl}`,
    `Browser: ${userAgent}`,
    `Records this session: ${total}`,
    `Panel window: newest ${entries.length} of ${PANEL_LIMIT} fetched`,
    `In this export: ${exported.length} (newest ${COPY_LIMIT})`,
    `Oldest exported record: ${first}`,
    '',
  ];
}

// Tallies over the loaded window, matching the panel's chips.
function statisticsSection(counts: DiagnosticCounts): string[] {
  return [
    '=== STATISTICS (loaded window) ===',
    `Errors: ${counts.errorCount}`,
    `Warnings: ${counts.warningCount}`,
    `Info: ${counts.infoCount}`,
    // Named apart from the three above because it counts runs, not
    // records: those three sum to the window, this one does not join them.
    // Server records stay in the export, but this is strictly a real-run count.
    `Distinct runs: ${counts.runCount}`,
    '',
  ];
}

// How to read a record — chiefly that `id` and `number` are different
// things, since only `id` cross-references `cosci logs`.
function legendSection(): string[] {
  return [
    '=== FIELD LEGEND ===',
    'id      - persisted store row id; what `cosci logs` and after_id',
    '          cursors speak. Gapped wherever hidden noise consumed ids.',
    'number  - position in the filtered stream, shown as "#N" in the panel.',
    'level   - error is ERROR/CRITICAL (40+), warning is WARNING (30),',
    '          info is everything below. levelName carries the exact name.',
    'run     - "Run <first 8 chars>", or "Server" when no run owns it.',
    '          The Runs statistic counts only distinct run-owned records.',
    'stage   - the emitting logger (app.run_stage, ui.error, uvicorn, ...).',
    'excText - formatted traceback, when the record carried one.',
    '',
  ];
}

/**
 * Renders the Copy payload: a context preamble followed by the newest
 * {@link COPY_LIMIT} entries as JSON under {@link EXPORT_LOGS_MARKER}.
 *
 * @param input The loaded entries plus the tallies and page context the
 *   preamble reports.
 * @returns The text to place on the clipboard.
 */
export function formatDiagnosticExport(input: DiagnosticExport): string {
  const context = input.context ?? {};
  const exported = input.entries.slice(-COPY_LIMIT);
  return [
    ...aboutSection(),
    ...tracksSection(),
    ...sessionSection(input, exported, context),
    ...statisticsSection(input.counts),
    ...legendSection(),
    EXPORT_LOGS_MARKER,
    JSON.stringify(exported, null, 2),
  ].join('\n');
}

/**
 * Reads the current page context for an export.
 *
 * @returns The URL and user agent when a DOM is present.
 */
export function browserExportContext(): DiagnosticExportContext {
  if (typeof window === 'undefined') return {};
  return {
    currentUrl: window.location.href,
    userAgent: window.navigator.userAgent,
  };
}

/** Where one report attempt has got to. */
export type ReportStatus = 'idle' | 'sending' | 'sent' | 'failed';

// How long the button holds its outcome before offering "Report" again.
// Longer than the Copy button's window because a failure has to be readable,
// not just noticed.
const OUTCOME_RESET_MS = 4_000;

/** What the button reads in each state. */
const REPORT_LABELS: Record<ReportStatus, string> = {
  idle: 'Report',
  sending: 'Sending…',
  sent: 'Sent',
  failed: "Couldn't send",
};

/** The button's label for a status. */
export function reportLabel(status: ReportStatus): string {
  return REPORT_LABELS[status];
}

/** The log window a report covers, as the panel is currently showing it. */
export interface ReportSubject {
  entries: DiagnosticLogEntry[];
  total: number;
  counts: DiagnosticCounts;
}

/**
 * Sends the panel's current view to the operator and reports how it went.
 *
 * The outcome is held on the button rather than announced in a toast: the
 * click happens inside the popover and the answer belongs next to it. A
 * failure is shown, never swallowed — a report that silently did not arrive
 * is worse than no button at all, since the scientist stops looking for
 * another way to tell anyone.
 */
export function useLogReport() {
  const [status, setStatus] = useState<ReportStatus>('idle');
  const timer = useResetTimer();

  function settle(outcome: ReportStatus) {
    setStatus(outcome);
    timer.schedule(() => setStatus('idle'), OUTCOME_RESET_MS);
  }

  async function send(subject: ReportSubject) {
    // A second click while the first is in flight would mail the same
    // window twice, which is the one thing the rate limit is there to
    // catch; catching it here keeps that budget for real reports.
    if (status === 'sending') return;
    // 'sending' is not a transient label, so any pending expiry from a
    // previous attempt is dropped rather than left to clear it.
    timer.cancel();
    setStatus('sending');
    try {
      await reportAppLogs(
        formatDiagnosticExport({...subject, context: browserExportContext()}),
      );
      settle('sent');
    } catch {
      settle('failed');
    }
  }

  return {status, send};
}
