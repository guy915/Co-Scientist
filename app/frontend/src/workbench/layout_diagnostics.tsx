import {useEffect, useMemo, useRef, useState} from 'react';
import {deleteAppLogs} from '@/api/logs';
import {copyText} from '@/lib/clipboard';
import {joinClasses} from './classes';
import {useResetTimer} from './hooks/use_reset_timer';
import {DiagnosticChips} from './layout_diagnostics_chips';
import {
  summarizeDiagnosticEntries,
  type DiagnosticCounts,
  type DiagnosticLogEntry,
} from './layout_diagnostics_data';
import {
  browserExportContext,
  formatDiagnosticExport,
} from './layout_diagnostics_export';
import {DiagnosticLogsHeader} from './layout_diagnostics_header';
import {useLogReport, type ReportStatus} from './layout_diagnostics_report';
import {
  useDiagnosticIngest,
  useNavigationLog,
  usePersistedAppLogs,
} from './layout_diagnostics_state';
import {useSystemStatus} from './hooks/system_status_context';
import {
  HeaderControlTrigger,
  headerControlButtonClasses,
  headerControlPopoverClasses,
  type HeaderControlProps,
} from './layout_primitives';

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
