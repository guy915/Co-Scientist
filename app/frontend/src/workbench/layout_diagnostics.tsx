import {useEffect, useMemo, useRef, useState} from 'react';
import {
  deleteAppLogs,
  APP_LOGS_CHANGED_EVENT,
  getAppLogs,
  postAppLogs,
  type AppLogsPayload,
} from '@/api/logs';
import {copyText} from '@/lib/clipboard';
import {joinClasses} from './classes';
import {useResetTimer} from './hooks/timers';
import {
  summarizeDiagnosticEntries,
  type DiagnosticCounts,
  type DiagnosticLogEntry,
  browserExportContext,
  formatDiagnosticExport,
  useLogReport,
  type ReportStatus,
  reportLabel,
  APP_LOGS_POLL_MS,
  buildAppLogEntry,
  detailToClientRecord,
  PANEL_LIMIT,
  type DiagnosticLogEventDetail,
  type PersistedAppLogs,
} from './layout_diagnostics_data';
import {useSystemStatus} from './hooks/system_status_context';
import {
  HeaderControlTrigger,
  headerControlButtonClasses,
  headerControlPopoverClasses,
  type HeaderControlProps,
} from './layout_primitives';
import {Icon, type IconName} from '@/components/icon';
import {tooltipClassNames} from './tooltip';
import {useLocation} from 'react-router-dom';
import {DIAGNOSTIC_EVENT} from './dom_events';

// Sizing/positioning for the logs popover: the shared header-control
// positioning prefix plus a logs-specific body capped to the viewport (dvh),
// with a narrower width override under the 700px breakpoint. The `!`
// overrides beat the shared .ucs-popover defaults applied by the parent's
// ShellPopover.
const LOGS_POPOVER_CLASSES = joinClasses(
  headerControlPopoverClasses('!w-[min(32rem,calc(100vw-2rem))]'),
  'max-h-[min(32rem,calc(100dvh-6rem))] grid-rows-[auto_auto_minmax(0,1fr)]',
  '!gap-0 overflow-hidden !border-cosci-logs-border !bg-cosci-logs-surface',
  'max-[700px]:right-[-0.5rem] ' +
    'max-[700px]:!w-[min(18.5rem,calc(100vw-1.5rem))]',
);

// The shared pill chrome, with the right side tightened around the badge.
const LOGS_BUTTON_CLASSES = headerControlButtonClasses(
  'px-[0.62rem] py-0 pl-[0.72rem]',
);

const LOGS_COUNT_CLASSES =
  'ucs-logs-count grid h-[1.38rem] min-w-[1.35rem] place-items-center ' +
  'rounded-full bg-cosci-logs-count-bg px-[0.42rem] text-[0.72rem] ' +
  'leading-none whitespace-nowrap';

const DIAGNOSTIC_INTRO_CLASSES =
  'ucs-diagnostic-intro border-b border-cosci-logs-border px-4 py-3';

// Never scrolls sideways: long unbroken tokens (dotted logger names, URLs)
// are contained by the grid tracks and the wrapping code block, so the only
// axis that can scroll is vertical.
const DIAGNOSTIC_LIST_CLASSES =
  'ucs-diagnostic-list grid min-h-0 gap-2 overflow-x-hidden overflow-y-auto ' +
  'px-4 pt-3 pb-4';

const DIAGNOSTIC_ENTRY_CLASSES = 'ucs-diagnostic-entry grid min-w-0 gap-1';

// The last (stage) track is minmax(0,auto) rather than auto so a long logger
// name shrinks and truncates instead of widening the grid past the panel.
const DIAGNOSTIC_ENTRY_META_CLASSES =
  'ucs-diagnostic-entry-meta grid min-w-0 ' +
  'grid-cols-[auto_auto_auto_minmax(0,1fr)_minmax(0,auto)] ' +
  'items-center gap-2 text-[0.72rem] font-semibold ' +
  'text-cosci-logs-meta ' +
  'max-[700px]:grid-cols-[auto_auto_auto_minmax(0,1fr)]';

const DIAGNOSTIC_ENTRY_RUN_CLASSES = 'truncate';

const DIAGNOSTIC_ENTRY_STAGE_CLASSES =
  'min-w-0 truncate max-[700px]:col-start-2 max-[700px]:col-end-[-1]';

// Payload blocks grow with their content: text wraps (including long
// unbroken tokens) and nothing scrolls inside an entry.
const DIAGNOSTIC_CODE_CLASSES =
  'm-0 rounded-[0.55rem] whitespace-pre-wrap [overflow-wrap:anywhere] ' +
  'bg-cosci-logs-panel-bg px-[0.7rem] py-[0.55rem] font-mono ' +
  'text-[0.72rem] leading-[1.3] text-cosci-logs-code-fg';

const DIAGNOSTIC_EMPTY_CLASSES =
  'ucs-diagnostic-empty m-0 rounded-[0.55rem] ' +
  'bg-cosci-logs-panel-bg px-[0.7rem] py-[0.55rem] text-center ' +
  'text-cosci-logs-panel-fg';

// Header "Logs" trigger button: the shared header-control pill, showing the
// running entry count as a badge. Kept as its own component so the count's
// two renderings — the badge and the accessible name, which a screen reader
// hears instead of the badge — stay side by side.
function LogsTriggerButton({
  open,
  count,
  onToggle,
}: {
  open: boolean;
  count: number;
  onToggle: () => void;
}) {
  return (
    <HeaderControlTrigger
      icon="expand_more"
      label="Logs"
      tooltip="Logs"
      open={open}
      onToggle={onToggle}
      ariaLabel={`Logs ${count}`}
      className={LOGS_BUTTON_CLASSES}
    >
      <span className={LOGS_COUNT_CLASSES}>{count}</span>
    </HeaderControlTrigger>
  );
}

// How long the Copy button reads "Copied" before returning to "Copy".
// Long enough to register as confirmation, short enough that the control
// never looks stuck — a second copy must not have to guess whether the
// label is stale.
const COPIED_RESET_MS = 2_000;

// Owns the transient "Copied" label: set it on a successful copy, and let
// it expire on its own. useResetTimer supplies the unmount cleanup and the
// replace-on-reschedule that keeps a rapid second copy from being cleared by
// the first one's pending timeout.
function useCopiedFlag() {
  const [copied, setCopied] = useState(false);
  const timer = useResetTimer();

  return {
    copied,
    markCopied() {
      setCopied(true);
      timer.schedule(() => setCopied(false), COPIED_RESET_MS);
    },
    resetCopied() {
      timer.cancel();
      setCopied(false);
    },
  };
}

// Everything the Copy/Clear handlers act on, bundled so the builder stays
// within the shared argument ceiling.
interface DiagnosticActionDeps {
  entries: DiagnosticLogEntry[];
  total: number;
  counts: DiagnosticCounts;
  copiedFlag: ReturnType<typeof useCopiedFlag>;
  bumpVersion: () => void;
}

// Builds the Copy/Clear handlers for the popover: Copy writes the export
// (context preamble + newest entries) to the clipboard, Clear deletes the
// persisted log server-side. Both flip local UI state the caller owns.
function makeDiagnosticActions({
  entries,
  total,
  counts,
  copiedFlag,
  bumpVersion,
}: DiagnosticActionDeps) {
  async function onCopy() {
    await copyText(
      formatDiagnosticExport({
        entries,
        total,
        counts,
        context: browserExportContext(),
      }),
    );
    copiedFlag.markCopied();
  }

  async function onClear() {
    try {
      await deleteAppLogs();
    } catch {
      // Unreachable API: leave the list as-is; the next poll re-syncs.
    }
    copiedFlag.resetCopied();
    bumpVersion();
  }

  return {onCopy, onClear};
}

/**
 * Header "Logs" button plus its diagnostics popover.
 *
 * The panel renders the persisted app-wide log — the same list on every
 * route, numbered by the store's consecutive ids. In-page diagnostic
 * events and route navigations are shipped to that log via the ingestion
 * endpoint, Clear deletes the persisted log (server-side), and Copy
 * exports a context preamble plus the newest entries (see
 * layout_diagnostics_export).
 */
export function DiagnosticsControl({
  open,
  onToggle,
  renderPopover,
}: HeaderControlProps) {
  // Bumped whenever the persisted log changed (ingest, navigation, clear)
  // so the fetch effect re-runs immediately instead of waiting for a poll.
  const [version, setVersion] = useState(0);
  const bumpVersion = () => setVersion(current => current + 1);
  const copiedFlag = useCopiedFlag(); // Copy button shows "Copied"
  const report = useLogReport(); // Report button shows how the send went
  const {status} = useSystemStatus();
  useDiagnosticIngest(bumpVersion);
  useNavigationLog(bumpVersion);
  const {entries, total} = usePersistedAppLogs(version, open);
  // Memoized on the entries array, which only changes when a load applies
  // — closed-state badge polls never pay for the tallies.
  const counts = useMemo(() => summarizeDiagnosticEntries(entries), [entries]);
  const {onCopy, onClear} = makeDiagnosticActions({
    entries,
    total,
    counts,
    copiedFlag,
    bumpVersion,
  });

  return (
    <>
      <LogsTriggerButton open={open} count={total} onToggle={onToggle} />
      {open &&
        renderPopover(
          <DiagnosticLogsPanel
            entries={entries}
            total={total}
            copied={copiedFlag.copied}
            counts={counts}
            reportStatus={report.status}
            canReport={status?.email_notifications_available ?? false}
            onClear={() => void onClear()}
            onCopy={() => void onCopy()}
            onReport={() => void report.send({entries, total, counts})}
          />,
          LOGS_POPOVER_CLASSES,
          'Diagnostic logs',
        )}
    </>
  );
}

// How close to the bottom (px) still counts as "pinned to the newest
// entry" for auto-follow purposes.
const PIN_THRESHOLD_PX = 24;

// Opening the panel lands on the newest entry (the list mounts pinned).
// After that, new records only auto-scroll while the user is still at the
// bottom — scrolling up to read must never be interrupted. `newestId` (not
// the count) drives the effect: at the window cap the count stops changing
// while the ids keep advancing.
function useAutoFollowScroll(newestId: number) {
  const listRef = useRef<HTMLDivElement>(null);
  const pinnedRef = useRef(true);

  useEffect(() => {
    const list = listRef.current;
    if (list && pinnedRef.current) list.scrollTop = list.scrollHeight;
  }, [newestId]);

  function onScroll() {
    const list = listRef.current;
    if (!list) return;
    const distanceFromBottom =
      list.scrollHeight - list.scrollTop - list.clientHeight;
    pinnedRef.current = distanceFromBottom <= PIN_THRESHOLD_PX;
  }

  return {listRef, onScroll};
}

// One entry's meta row (id/time/level/run/stage) plus its JSON payload.
function DiagnosticLogEntryRow({entry}: {entry: DiagnosticLogEntry}) {
  return (
    <article className={DIAGNOSTIC_ENTRY_CLASSES}>
      <div className={DIAGNOSTIC_ENTRY_META_CLASSES}>
        <span>#{entry.number}</span>
        <span>[{entry.time}]</span>
        <span>{entry.levelName}</span>
        <span className={DIAGNOSTIC_ENTRY_RUN_CLASSES}>{entry.run}</span>
        <strong className={DIAGNOSTIC_ENTRY_STAGE_CLASSES}>
          {entry.stage}:
        </strong>
      </div>
      <pre className={DIAGNOSTIC_CODE_CLASSES}>
        {entry.excText ? `${entry.message}\n\n${entry.excText}` : entry.message}
      </pre>
    </article>
  );
}

// Scrolling list of log entries (each entry's id/time/run/stage meta row plus
// its JSON payload), or an empty-state message when there are none.
function DiagnosticLogList({entries}: {entries: DiagnosticLogEntry[]}) {
  const newestId = entries.length ? entries[entries.length - 1].id : 0;
  const {listRef, onScroll} = useAutoFollowScroll(newestId);

  return (
    <div
      ref={listRef}
      onScroll={onScroll}
      className={DIAGNOSTIC_LIST_CLASSES}
      aria-label="Log events"
    >
      {entries.map(entry => (
        <DiagnosticLogEntryRow key={entry.id} entry={entry} />
      ))}
      {entries.length === 0 && (
        <p className={DIAGNOSTIC_EMPTY_CLASSES}>No diagnostic events loaded.</p>
      )}
    </div>
  );
}

// Presentational body of the popover: the header (title + Clear/Copy
// actions), summary count chips, and the scrolling entry list. All state
// stays in DiagnosticsControl; this only renders what it is handed.
function DiagnosticLogsPanel({
  entries,
  total,
  copied,
  counts,
  reportStatus,
  canReport,
  onClear,
  onCopy,
  onReport,
}: {
  entries: DiagnosticLogEntry[];
  total: number;
  copied: boolean;
  counts: DiagnosticCounts;
  reportStatus: ReportStatus;
  canReport: boolean;
  onClear: () => void;
  onCopy: () => void;
  onReport: () => void;
}) {
  return (
    <>
      <DiagnosticLogsHeader
        copied={copied}
        reportStatus={reportStatus}
        canReport={canReport}
        onClear={onClear}
        onCopy={onCopy}
        onReport={onReport}
      />
      <div className={DIAGNOSTIC_INTRO_CLASSES}>
        <DiagnosticChips total={total} shown={entries.length} counts={counts} />
      </div>
      <DiagnosticLogList entries={entries} />
    </>
  );
}

// The Logs popover's summary chip row: the session size, the three level
// bands, and the number of distinct real runs behind them. Split out of
// layout_diagnostics.tsx to keep that module under the file-length
// ceiling; it is presentational only and owns no state.

const CHIPS_ROW_CLASSES =
  'ucs-diagnostic-chips flex flex-wrap items-center gap-[0.45rem]';

const CHIP_CLASSES =
  'rounded-full bg-cosci-logs-accent-bg px-2 py-[0.15rem] ' +
  'text-[0.7rem] font-semibold whitespace-nowrap ' +
  'text-cosci-logs-accent-fg';

const ERROR_CHIP_CLASSES =
  'rounded-full bg-cosci-logs-danger-bg px-2 py-[0.15rem] ' +
  'text-[0.7rem] font-semibold whitespace-nowrap ' +
  'text-cosci-logs-danger-fg';

const WARN_CHIP_CLASSES =
  'rounded-full bg-cosci-logs-warn-bg px-2 py-[0.15rem] ' +
  'text-[0.7rem] font-semibold whitespace-nowrap ' +
  'text-cosci-logs-warn-fg';

// Separates the record tallies from the run count, which is not one of
// them (see below).
const DIVIDER_CLASSES = 'mx-[0.15rem] h-3 w-px bg-cosci-border';

/**
 * The record tallies, which are meant to be read as a sum.
 *
 * Every record shown carries exactly one level, so Errors + Warnings +
 * Info is the number of rows in the list. That identity is the whole
 * point of the row, and it only holds against the rows actually loaded:
 * `total` counts the session's entire filtered stream, of which the panel
 * fetches the newest hundred. Past that the bands stop summing to Total,
 * so a "Showing" chip appears and the bands are read against it instead
 * of silently disagreeing with the number beside them.
 */
function recordChips(
  total: number,
  shown: number,
  counts: DiagnosticCounts,
): [string, number, string][] {
  const toned = (count: number, tone: string) => (count ? tone : CHIP_CLASSES);
  return [
    ['Total', total, CHIP_CLASSES],
    ...(shown < total
      ? ([['Showing', shown, CHIP_CLASSES]] as [string, number, string][])
      : []),
    ['Errors', counts.errorCount, toned(counts.errorCount, ERROR_CHIP_CLASSES)],
    [
      'Warnings',
      counts.warningCount,
      toned(counts.warningCount, WARN_CHIP_CLASSES),
    ],
    ['Info', counts.infoCount, CHIP_CLASSES],
  ];
}

/**
 * Renders the popover's summary chips.
 *
 * The run count is deliberately set apart, after a divider and written as
 * a noun ("1 run"), because it counts runs and every chip before it
 * counts records. As a fifth "Runs 1" chip in the same ledger it read as
 * a fourth level band, and the row looked like it had failed to add up --
 * 38 + 2 + 1 against a total of 40.
 *
 * @param props.total Records added this browsing session.
 * @param props.shown Records currently loaded, which the bands tally.
 * @param props.counts Per-level tallies plus the distinct-run count.
 */
export function DiagnosticChips({
  total,
  shown,
  counts,
}: {
  total: number;
  shown: number;
  counts: DiagnosticCounts;
}) {
  return (
    <div className={CHIPS_ROW_CLASSES}>
      {recordChips(total, shown, counts).map(([label, count, className]) => (
        <span key={label} className={className}>
          {label} {count}
        </span>
      ))}
      <span aria-hidden="true" className={DIVIDER_CLASSES} />
      <span className={CHIP_CLASSES}>
        {counts.runCount} {counts.runCount === 1 ? 'run' : 'runs'}
      </span>
    </div>
  );
}

const DIAGNOSTIC_HEADER_CLASSES =
  'ucs-diagnostic-header flex items-center justify-between gap-3 border-b ' +
  'border-cosci-logs-border px-4 py-3 ' +
  'max-[700px]:flex-col max-[700px]:items-start';

const DIAGNOSTIC_TITLE_CLASSES =
  'm-0 text-base font-semibold leading-tight text-cosci-logs-heading';

const DIAGNOSTIC_ACTIONS_CLASSES =
  'ucs-diagnostic-actions flex flex-nowrap gap-[0.45rem]';

const DIAGNOSTIC_ACTION_BUTTON_CLASSES =
  'inline-flex min-h-8 cursor-pointer items-center gap-[0.3rem] rounded-full ' +
  'border border-cosci-logs-action-border ' +
  'bg-cosci-logs-action-bg px-[0.75rem] text-[0.82rem] font-semibold ' +
  'whitespace-nowrap text-cosci-logs-action-fg ' +
  'hover:bg-cosci-logs-action-hover ' +
  'focus-visible:bg-cosci-logs-action-hover ' +
  // Dimmed and inert-looking when it cannot act, so "why is nothing
  // happening" is answered before the click rather than after it. The
  // tooltip still fires: :hover matches a disabled button, which is the
  // whole reason the explanation can live there.
  'disabled:cursor-default disabled:opacity-45 ' +
  'disabled:hover:bg-cosci-logs-action-bg';

// One Clear/Copy/Report button in the header's actions row. A disabled
// action keeps its tooltip so the reason it cannot be used is one hover
// away rather than a guess.
function DiagnosticActionButton({
  icon,
  label,
  onClick,
  disabled,
  tooltip,
}: {
  icon: IconName;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  tooltip?: string;
}) {
  return (
    <button
      type="button"
      className={
        tooltip
          ? tooltipClassNames({
              className: DIAGNOSTIC_ACTION_BUTTON_CLASSES,
              placement: 'bottom',
              wrap: true,
            })
          : DIAGNOSTIC_ACTION_BUTTON_CLASSES
      }
      data-tooltip={tooltip}
      disabled={disabled}
      onClick={onClick}
    >
      <Icon aria-hidden="true" className="text-base" name={icon} />
      <span>{label}</span>
    </button>
  );
}

// One entry in the header's actions row.
interface DiagnosticAction {
  id: string;
  icon: IconName;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  tooltip?: string;
}

// What the Report action offers, given whether the server can send mail at
// all. Disabled rather than hidden: the way to get diagnostics to the
// maintainer should be visible even on a deployment that cannot yet mail
// them, with the reason attached — and Copy is right beside it.
function reportAction(
  status: ReportStatus,
  canReport: boolean,
  onReport: () => void,
): DiagnosticAction {
  return {
    id: 'report',
    icon: 'send',
    label: reportLabel(status),
    onClick: onReport,
    disabled: !canReport || status === 'sending',
    tooltip: canReport
      ? 'Email these logs to the maintainer'
      : 'Email delivery is not configured on this server',
  };
}

// Popover header: the "Diagnostic Logs" title plus the Clear/Copy/Report
// actions.
export function DiagnosticLogsHeader({
  copied,
  reportStatus,
  canReport,
  onClear,
  onCopy,
  onReport,
}: {
  copied: boolean;
  reportStatus: ReportStatus;
  canReport: boolean;
  onClear: () => void;
  onCopy: () => void;
  onReport: () => void;
}) {
  const actions: DiagnosticAction[] = [
    {id: 'clear', icon: 'refresh', label: 'Clear', onClick: onClear},
    {
      id: 'copy',
      icon: 'content_copy',
      label: copied ? 'Copied' : 'Copy',
      onClick: onCopy,
    },
    reportAction(reportStatus, canReport, onReport),
  ];

  return (
    <div className={DIAGNOSTIC_HEADER_CLASSES}>
      <div className="ucs-diagnostic-title">
        <h2 className={DIAGNOSTIC_TITLE_CLASSES}>Diagnostic Logs</h2>
      </div>
      <div className={DIAGNOSTIC_ACTIONS_CLASSES}>
        {actions.map(action => (
          <DiagnosticActionButton key={action.id} {...action} />
        ))}
      </div>
    </div>
  );
}

// The last stream state applied to `logs`: whether display entries were
// built for it (only true while the panel is open, since a closed-state
// poll only needs the badge total). A load whose payload matches — and
// whose entries the current open state is not missing — applies nothing,
// so background polls of an unchanged log never re-render.
interface AppliedLogState {
  lastId: number;
  total: number;
  withEntries: boolean;
}

// Where this browsing session began in the durable, app-wide log: the
// log's high-water id at session start, so a record belongs to this
// session only when its id is above it. The panel shows only those, so
// opening the site starts on a clean panel instead of the whole retained
// history. The anchor is all this holds — every request pages from it and
// the server reports `session_total` for exactly that window, so nothing
// here has to reconstruct a count by arithmetic.
//
// The baseline lives in sessionStorage, not in this module's memory,
// because the two events look identical to a module-scoped variable but
// mean opposite things to a reader: closing the tab (or the browser) ends
// the session and should start clean, while reloading the tab is the
// reflex for "did that just get logged?" and must not throw the log away.
// sessionStorage draws exactly that line — it survives a reload of this
// tab and dies with it — and it is per-tab, so two tabs keep their own
// views of the same durable log.
const BASELINE_KEY = 'cosci-logs-session-baseline';

interface SessionBaseline {
  id: number;
}

// Storage can be unavailable or full (private modes, quota); the baseline
// is a convenience, never a reason to break the panel, so every access
// degrades to this process's memory.
let memoryBaseline: SessionBaseline | null = null;

function readBaseline(): SessionBaseline | null {
  try {
    const raw = window.sessionStorage.getItem(BASELINE_KEY);
    if (raw) return JSON.parse(raw) as SessionBaseline;
  } catch {
    // Unreadable storage: fall back to the in-memory copy.
  }
  return memoryBaseline;
}

function writeBaseline(baseline: SessionBaseline): void {
  memoryBaseline = baseline;
  try {
    window.sessionStorage.setItem(BASELINE_KEY, JSON.stringify(baseline));
  } catch {
    // Unwritable storage: the in-memory copy still holds for this load.
  }
}

// Clears the captured session baseline. For tests, which drive many
// independent "page sessions" through one module instance.
export function resetSessionBaselineForTest(): void {
  memoryBaseline = null;
  try {
    window.sessionStorage.removeItem(BASELINE_KEY);
  } catch {
    // Nothing to clear.
  }
}

// The id to page from: everything at or below the session baseline is
// pre-session and never fetched. Zero until the first load of a session
// establishes it.
export function sessionAfterId(): number {
  return readBaseline()?.id ?? 0;
}

// Captures the session baseline from the first payload of a session, and
// re-captures it after a full clear restarts ids below the baseline
// (which would otherwise hide everything forever). Called before the load
// effect's disposed/latest guards on purpose: the baseline is a
// session-global snapshot, and letting a disposed mount load fall through
// without recording it would let a later load capture a baseline that
// already includes this session's own records.
function ensureSessionBaseline(payload: AppLogsPayload): void {
  const baseline = readBaseline();
  if (baseline === null || payload.last_id < baseline.id) {
    writeBaseline({id: payload.last_id});
  }
}

// Builds the next applied-state marker and displayed logs from a fresh
// payload, scoped to this browsing session.
//
// Only records added after the baseline are shown, so the establishing
// load (whose records all predate the baseline) naturally shows nothing —
// no special case needed. The request already pages from the baseline,
// and the cap is re-enforced here so the panel shows at most the newest
// PANEL_LIMIT. Numbers backwards from the session total so the newest row
// is always `total` (a capped window shows 151..250, not 1..100).
//
// The count is the server's `session_total` for the window this request
// asked for, never a subtraction off the whole-table `total`: retention
// pruning and a scoped clear both delete rows the snapshot had counted,
// so the difference goes negative and the badge sticks at zero while rows
// keep rendering underneath it.
function buildLoadedLogs(
  payload: AppLogsPayload,
  open: boolean,
  requestAfterId: number,
): {applied: AppliedLogState; logs: PersistedAppLogs} {
  const baseline = readBaseline() ?? {id: payload.last_id};
  const session = payload.logs.filter(record => record.id > baseline.id);
  // A request issued before the current anchor existed — the establishing
  // load, or one racing the re-anchor after an operator Clear restarts ids
  // — counted pre-session rows, so it contributes nothing to this session.
  const total = requestAfterId < baseline.id ? 0 : payload.session_total;
  const shown = open ? session.slice(-PANEL_LIMIT) : [];
  const first = total - shown.length + 1;
  return {
    applied: {lastId: payload.last_id, total, withEntries: open},
    logs: {
      entries: shown.map((record, index) =>
        buildAppLogEntry(record, first + index),
      ),
      total,
    },
  };
}

// True when `next` is already reflected in `applied` for the current open
// state, so a background poll of an unchanged session never re-renders.
function isAlreadyApplied(
  applied: AppliedLogState | null,
  next: AppliedLogState,
  open: boolean,
): boolean {
  return (
    applied !== null &&
    applied.lastId === next.lastId &&
    applied.total === next.total &&
    (applied.withEntries || !open)
  );
}

// Fetches this browsing session's slice of the app-wide persisted log: on
// mount (so the badge count is real), whenever `version` bumps (Clear
// changed the store), whenever the api layer announces a change (a click
// or error was just persisted), and on a steady background poll — popover
// open or not, so the badge never depends on opening the panel. Every
// load pages from the session baseline, so pre-session history is never
// fetched however deep the retained log is; the session count stays cheap
// to keep current whether the panel is open or closed. The same fetch
// runs on every route, so navigating never changes what the panel shows.
// Wires `load` to run once immediately, on a steady background poll at
// `intervalMs` (a hidden tab loads nothing; foregrounding runs one
// immediate catch-up load rather than waiting out the interval), and
// whenever the api layer announces the persisted log changed. Returns the
// cleanup.
function subscribeToLogPolling(
  load: () => void,
  intervalMs: number,
): () => void {
  load();
  const loadIfVisible = () => {
    if (!document.hidden) load();
  };
  const timer = window.setInterval(loadIfVisible, intervalMs);
  document.addEventListener('visibilitychange', loadIfVisible);
  window.addEventListener(APP_LOGS_CHANGED_EVENT, load);
  return () => {
    window.clearInterval(timer);
    document.removeEventListener('visibilitychange', loadIfVisible);
    window.removeEventListener(APP_LOGS_CHANGED_EVENT, load);
  };
}

// What one effect generation's loader writes to, bundled so the loader
// stays a plain function rather than a closure over the hook body.
interface LogLoaderDeps {
  open: boolean;
  applied: {current: AppliedLogState | null};
  setLogs: (logs: PersistedAppLogs) => void;
}

// Builds the loader for one effect generation, plus the `dispose` that
// retires it. Responses of a disposed generation are dropped rather than
// applied to a remounted panel.
function makeLogLoader({open, applied, setLogs}: LogLoaderDeps) {
  let disposed = false;
  // Requests can resolve out of order (an announce-triggered load can
  // race the poll); only the most recently issued request may apply.
  let latestRequest = 0;
  const load = () => {
    const request = ++latestRequest;
    // The anchor this request pages from, kept so the response is read
    // against the anchor that was current when it was issued.
    const afterId = sessionAfterId();
    // Always page the newest PANEL_LIMIT of the session (from the
    // baseline), so the badge count is right whether the panel is open
    // or closed; only display entries are gated on `open`.
    getAppLogs(afterId, PANEL_LIMIT)
      .then(payload => {
        // Record the baseline before the guards: a disposed mount load
        // must still anchor the session, or a later load anchors it to a
        // payload that already contains this session's records.
        ensureSessionBaseline(payload);
        if (disposed || request !== latestRequest) return;
        const next = buildLoadedLogs(payload, open, afterId);
        if (isAlreadyApplied(applied.current, next.applied, open)) return;
        applied.current = next.applied;
        setLogs(next.logs);
      })
      .catch(() => {
        if (disposed || request !== latestRequest) return;
        applied.current = null;
        setLogs({entries: [], total: 0});
      });
  };
  return {
    load,
    dispose() {
      disposed = true;
    },
  };
}

export function usePersistedAppLogs(
  version: number,
  open: boolean,
): PersistedAppLogs {
  const [logs, setLogs] = useState<PersistedAppLogs>({
    entries: [],
    total: 0,
  });
  const appliedRef = useRef<AppliedLogState | null>(null);

  useEffect(() => {
    const {load, dispose} = makeLogLoader({
      open,
      applied: appliedRef,
      setLogs,
    });
    // `open` is already a dependency, so flipping the panel re-subscribes
    // at the other cadence instead of needing a second timer.
    const unsubscribe = subscribeToLogPolling(
      load,
      open ? APP_LOGS_POLL_MS.open : APP_LOGS_POLL_MS.closed,
    );
    return () => {
      dispose();
      unsubscribe();
    };
  }, [version, open]);

  return logs;
}

// Ships `cosci-diagnostic-event` CustomEvents dispatched anywhere in the
// app to the persisted log, then notifies the caller so the list can
// refresh. Subscribed for the component's whole lifetime (not only while
// the popover is open) so no event is lost.
export function useDiagnosticIngest(onIngested: () => void) {
  const onIngestedRef = useRef(onIngested);
  onIngestedRef.current = onIngested;

  useEffect(() => {
    function onDiagnosticEvent(event: Event) {
      const custom = event as CustomEvent<DiagnosticLogEventDetail>;
      if (!custom.detail?.stage) return; // ignore malformed events
      postAppLogs([detailToClientRecord(custom.detail)])
        .then(() => onIngestedRef.current())
        .catch(() => {
          // Offline or API down: drop the event rather than break the page.
        });
    }
    window.addEventListener(DIAGNOSTIC_EVENT, onDiagnosticEvent);
    return () => {
      window.removeEventListener(DIAGNOSTIC_EVENT, onDiagnosticEvent);
    };
  }, []);
}

// Persists page loads and route changes into the same log, so UI
// navigation shows up next to backend records.
export function useNavigationLog(onIngested: () => void) {
  const {pathname} = useLocation();
  const onIngestedRef = useRef(onIngested);
  onIngestedRef.current = onIngested;
  const lastLogged = useRef<string | null>(null);

  useEffect(() => {
    if (lastLogged.current === pathname) return;
    const message =
      lastLogged.current === null
        ? `page loaded at ${pathname}`
        : `navigated to ${pathname}`;
    lastLogged.current = pathname;
    postAppLogs([{message, logger: 'navigation'}])
      .then(() => onIngestedRef.current())
      .catch(() => {
        // Offline or API down: navigation logging is best-effort.
      });
  }, [pathname]);
}
