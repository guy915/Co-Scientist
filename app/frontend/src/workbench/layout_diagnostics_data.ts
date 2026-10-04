import {
  type AppLogRecord,
  type ClientLogRecord,
  reportAppLogs,
} from '@/api/logs';
import {useState} from 'react';
import {useResetTimer} from './hooks/timers';

export type DiagnosticLogLevel = 'info' | 'warning' | 'error';

export interface DiagnosticLogEntry {
  id: number;
  // Filtered display positions differ from global store IDs, whose hidden/noise
  // records leave gaps.
  number: number;
  time: string;
  run: string;
  stage: string;
  level: DiagnosticLogLevel;
  levelName: string;
  message: string;
  excText: string | null;
  payload: Record<string, unknown>;
}

// Server-owned records must not inflate the distinct research-run count.
export const SERVER_LOG_SOURCE = 'Server';

// Copy the whole loaded panel window so diagnostic export cannot cut its
// narrative short.
export const COPY_LIMIT = 100;

export const PANEL_LIMIT = 100;

// Closed badges poll more slowly to reduce steady-state database work; open
// panels remain live.
export const APP_LOGS_POLL_MS = {open: 2_000, closed: 5_000};

export interface DiagnosticLogEventDetail {
  // Use the actual run ID, never a goal-derived title: this field is persisted
  // and served through the API.
  runId?: string;
  stage: string;
  level?: DiagnosticLogLevel;
  payload?: Record<string, unknown>;
}

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

function clientLevel(level: DiagnosticLogLevel | undefined): string {
  return level === 'error' || level === 'warning' ? level : 'info';
}

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

function appLogLevel(record: AppLogRecord): DiagnosticLogLevel {
  if (record.levelno >= 40) return 'error';
  return record.levelno >= 30 ? 'warning' : 'info';
}

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
    runCount: new Set(
      entries.map(({run}) => run).filter(run => run !== SERVER_LOG_SOURCE),
    ).size,
  };
}

// A pasted array lacks provenance/filter/ID context; keep the export preamble
// alongside its sliceable JSON marker.

export const EXPORT_LOGS_MARKER = '=== LOGS (JSON) ===';

export interface DiagnosticExportContext {
  currentUrl?: string;
  userAgent?: string;
  exportedAt?: Date;
}

export interface DiagnosticExport {
  entries: DiagnosticLogEntry[];
  total: number;
  counts: DiagnosticCounts;
  context?: DiagnosticExportContext;
}

const UNAVAILABLE = 'Unavailable';

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
    '  view but available from GET /api/logs?verbose=1',
    '- verbatim repeats of a record within a 10-minute window',
    '',
  ];
}

function resolveContext(context: DiagnosticExportContext) {
  return {
    exportedAt: (context.exportedAt ?? new Date()).toLocaleString(),
    currentUrl: context.currentUrl ?? UNAVAILABLE,
    userAgent: context.userAgent ?? UNAVAILABLE,
  };
}

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

function statisticsSection(counts: DiagnosticCounts): string[] {
  return [
    '=== STATISTICS (loaded window) ===',
    `Errors: ${counts.errorCount}`,
    `Warnings: ${counts.warningCount}`,
    `Info: ${counts.infoCount}`,
    `Distinct runs: ${counts.runCount}`,
    '',
  ];
}

function legendSection(): string[] {
  return [
    '=== FIELD LEGEND ===',
    'id      - persisted store row id used by API after_id cursors.',
    '          Gapped wherever hidden noise consumed ids.',
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

export function browserExportContext(): DiagnosticExportContext {
  if (typeof window === 'undefined') return {};
  return {
    currentUrl: window.location.href,
    userAgent: window.navigator.userAgent,
  };
}

export type ReportStatus = 'idle' | 'sending' | 'sent' | 'failed';

// Failures need a longer readable outcome window than copy confirmation.
const OUTCOME_RESET_MS = 4_000;

const REPORT_LABELS: Record<ReportStatus, string> = {
  idle: 'Report',
  sending: 'Sending…',
  sent: 'Sent',
  failed: "Couldn't send",
};

export function reportLabel(status: ReportStatus): string {
  return REPORT_LABELS[status];
}

export interface ReportSubject {
  entries: DiagnosticLogEntry[];
  total: number;
  counts: DiagnosticCounts;
}

// Report failures must remain visible beside their action; silent failure would
// falsely assure the scientist it arrived.
export function useLogReport() {
  const [status, setStatus] = useState<ReportStatus>('idle');
  const timer = useResetTimer();

  function settle(outcome: ReportStatus) {
    setStatus(outcome);
    timer.schedule(() => setStatus('idle'), OUTCOME_RESET_MS);
  }

  async function send(subject: ReportSubject) {
    // Duplicate clicks would mail the same window and waste its reporting-rate
    // allowance.
    if (status === 'sending') return;
    // An earlier outcome expiry must not clear the non-transient sending state.
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
