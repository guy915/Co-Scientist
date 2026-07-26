// Serializes the Logs panel's entries for the Copy action.
//
// A bare JSON array is machine-readable but says nothing about what the
// log is, what it deliberately omits, or how its two id columns differ —
// context a maintainer (or a coding agent) reading a pasted export has no
// other way to recover. The export is therefore a human-readable preamble
// followed by the same JSON entries under a marker line, so it stays
// pasteable into an issue and sliceable back into data.
import {
  COPY_LIMIT,
  PANEL_LIMIT,
  type DiagnosticCounts,
  type DiagnosticLogEntry,
} from './layout_diagnostics_data';

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
    // Server records stay in the export, but this is strictly a real-run count.
    `Runs: ${counts.runCount}`,
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
