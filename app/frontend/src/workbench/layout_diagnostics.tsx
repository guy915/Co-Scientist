import {useEffect, useMemo, useRef, useState} from 'react';
import {
  deleteAppLogs,
  APP_LOGS_CHANGED_EVENT,
  getAppLogs,
  postAppLogs,
  type AppLogsPayload,
} from '@/api/logs';
import {copyText} from '@/lib/clipboard';
import {joinClasses, tooltipClassNames} from './classes';
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
import {useLocation} from 'react-router-dom';
import {DIAGNOSTIC_EVENT} from './dom_events';

// Important sizing overrides must outrank the shared ShellPopover defaults.
const LOGS_POPOVER_CLASSES = joinClasses(
  headerControlPopoverClasses('!w-[min(32rem,calc(100vw-2rem))]'),
  'max-h-[min(32rem,calc(100dvh-6rem))] grid-rows-[auto_auto_minmax(0,1fr)]',
  '!gap-0 overflow-hidden !border-cosci-logs-border !bg-cosci-logs-surface',
  'max-[700px]:right-[-0.5rem] ' +
    'max-[700px]:!w-[min(18.5rem,calc(100vw-1.5rem))]',
);

const LOGS_BUTTON_CLASSES = headerControlButtonClasses(
  'px-[0.62rem] py-0 pl-[0.72rem]',
);

const LOGS_COUNT_CLASSES =
  'ucs-logs-count grid h-[1.38rem] min-w-[1.35rem] place-items-center ' +
  'rounded-full bg-cosci-logs-count-bg px-[0.42rem] text-[0.72rem] ' +
  'leading-none whitespace-nowrap';

const DIAGNOSTIC_INTRO_CLASSES =
  'ucs-diagnostic-intro border-b border-cosci-logs-border px-4 py-3';

const DIAGNOSTIC_LIST_CLASSES =
  'ucs-diagnostic-list grid min-h-0 gap-2 overflow-x-hidden overflow-y-auto ' +
  'px-4 pt-3 pb-4';

const DIAGNOSTIC_ENTRY_CLASSES = 'ucs-diagnostic-entry grid min-w-0 gap-1';

// Shrinkable grid tracks prevent long logger names from widening the panel.
const DIAGNOSTIC_ENTRY_META_CLASSES =
  'ucs-diagnostic-entry-meta grid min-w-0 ' +
  'grid-cols-[auto_auto_auto_minmax(0,1fr)_minmax(0,auto)] ' +
  'items-center gap-2 text-[0.72rem] font-semibold ' +
  'text-cosci-logs-meta ' +
  'max-[700px]:grid-cols-[auto_auto_auto_minmax(0,1fr)]';

const DIAGNOSTIC_ENTRY_RUN_CLASSES = 'truncate';

const DIAGNOSTIC_ENTRY_STAGE_CLASSES =
  'min-w-0 truncate max-[700px]:col-start-2 max-[700px]:col-end-[-1]';

const DIAGNOSTIC_CODE_CLASSES =
  'm-0 rounded-[0.55rem] whitespace-pre-wrap [overflow-wrap:anywhere] ' +
  'bg-cosci-logs-panel-bg px-[0.7rem] py-[0.55rem] font-mono ' +
  'text-[0.72rem] leading-[1.3] text-cosci-logs-code-fg';

const DIAGNOSTIC_EMPTY_CLASSES =
  'ucs-diagnostic-empty m-0 rounded-[0.55rem] ' +
  'bg-cosci-logs-panel-bg px-[0.7rem] py-[0.55rem] text-center ' +
  'text-cosci-logs-panel-fg';

// Keep the badge count and accessible name together so screen readers hear the
// same tally.
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
    resetCopied() {
      timer.cancel();
      setCopied(false);
    },
  };
}

interface DiagnosticActionDeps {
  entries: DiagnosticLogEntry[];
  total: number;
  counts: DiagnosticCounts;
  copiedFlag: ReturnType<typeof useCopiedFlag>;
  bumpVersion: () => void;
}

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
      // API failure leaves the visible list intact until a later poll succeeds.
    }
    copiedFlag.resetCopied();
    bumpVersion();
  }

  return {onCopy, onClear};
}

export function DiagnosticsControl({
  open,
  onToggle,
  renderPopover,
}: HeaderControlProps) {
  const [version, setVersion] = useState(0);
  const bumpVersion = () => setVersion(current => current + 1);
  const copiedFlag = useCopiedFlag();
  const report = useLogReport();
  const {status} = useSystemStatus();
  useDiagnosticIngest(bumpVersion);
  useNavigationLog(bumpVersion);
  const {entries, total} = usePersistedAppLogs(version, open);
  // Closed-state badge polls need no entry tallies until a new window applies.
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

const PIN_THRESHOLD_PX = 24;

// Open on the newest entry, then respect readers scrolled upward; follow the
// newest ID because a capped count stops changing.
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

const DIVIDER_CLASSES = 'mx-[0.15rem] h-3 w-px bg-cosci-border';

// Level bands sum only to the loaded window, not the uncapped session total;
// show that window size once capped.
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

// Distinct runs are not another record band; separate their count from level
// tallies.
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
  // Disabled buttons still match hover, so their unavailable-action explanation
  // remains reachable.
  'disabled:cursor-default disabled:opacity-45 ' +
  'disabled:hover:bg-cosci-logs-action-bg';

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

interface DiagnosticAction {
  id: string;
  icon: IconName;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  tooltip?: string;
}

// Keep Report discoverable even without SMTP, with its reason and the Copy
// alternative visible.
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

interface AppliedLogState {
  lastId: number;
  total: number;
  withEntries: boolean;
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

// Feedback shares the panel's session anchor and exporter. Include operational
// records hidden by the panel's noise view without changing that view.
export async function sessionDiagnosticExport(): Promise<string> {
  let entries: DiagnosticLogEntry[] = [];
  let total = 0;
  try {
    const afterId = sessionAfterId();
    const payload = await getAppLogs(afterId, PANEL_LIMIT, true);
    ensureSessionBaseline(payload);
    const loaded = buildLoadedLogs(payload, true, afterId).logs;
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

// Re-anchor when clear restarts IDs. Capture before disposal guards so a
// discarded mount cannot make later loads hide session records.
function ensureSessionBaseline(payload: AppLogsPayload): void {
  const baseline = readBaseline();
  if (baseline === null || payload.last_id < baseline.id) {
    writeBaseline({id: payload.last_id});
  }
}

// Use server session_total: subtracting table totals breaks after
// retention/scoped clears. Number the newest row by that uncapped total.
function buildLoadedLogs(
  payload: AppLogsPayload,
  open: boolean,
  requestAfterId: number,
): {applied: AppliedLogState; logs: PersistedAppLogs} {
  const baseline = readBaseline() ?? {id: payload.last_id};
  const session = payload.logs.filter(record => record.id > baseline.id);
  // Responses issued before the current anchor counted pre-session rows and
  // must contribute nothing.
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

interface LogLoaderDeps {
  open: boolean;
  applied: {current: AppliedLogState | null};
  setLogs: (logs: PersistedAppLogs) => void;
}

// Drop responses from disposed generations instead of applying to a remounted
// panel.
function makeLogLoader({open, applied, setLogs}: LogLoaderDeps) {
  let disposed = false;
  // Polling and write-triggered loads race; only the latest issued request may
  // apply.
  let latestRequest = 0;
  const load = () => {
    const request = ++latestRequest;
    // Read the response against the anchor captured at issuance, even if a
    // clear re-anchored during the request.
    const afterId = sessionAfterId();
    getAppLogs(afterId, PANEL_LIMIT)
      .then(payload => {
        // Even a disposed mount load must establish the global session anchor
        // before a later response includes session-owned records.
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

// Ingest throughout the shell lifetime so closing the popover cannot lose
// diagnostic events.
export function useDiagnosticIngest(onIngested: () => void) {
  const onIngestedRef = useRef(onIngested);
  onIngestedRef.current = onIngested;

  useEffect(() => {
    function onDiagnosticEvent(event: Event) {
      const custom = event as CustomEvent<DiagnosticLogEventDetail>;
      if (!custom.detail?.stage) return;
      postAppLogs([detailToClientRecord(custom.detail)])
        .then(() => onIngestedRef.current())
        .catch(() => {
          // Failed diagnostic ingestion must not break the page.
        });
    }
    window.addEventListener(DIAGNOSTIC_EVENT, onDiagnosticEvent);
    return () => {
      window.removeEventListener(DIAGNOSTIC_EVENT, onDiagnosticEvent);
    };
  }, []);
}

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
        // Navigation logging must remain best-effort when the API is down.
      });
  }, [pathname]);
}
