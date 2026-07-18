import {useEffect, useRef, useState, type ReactNode} from 'react';
import {useLocation} from 'react-router-dom';
import {
  deleteAppLogs,
  getAppLogs,
  postAppLogs,
  type AppLogRecord,
  type ClientLogRecord,
} from '@/api/logs';
import {Icon, type IconName} from '@/components/icon';
import {copyText} from '@/lib/clipboard';
import {joinClasses} from './classes';
import {DIAGNOSTIC_EVENT} from './dom_events';
import {tooltipClassNames} from './tooltip';

type DiagnosticLogLevel = 'info' | 'success' | 'error';

// One rendered row in the Logs panel. Every entry comes from the single
// persisted app-wide log (the backend's app_logs table): backend records
// are captured server-side, and in-page diagnostic events are POSTed to
// the same log before being re-fetched. That keeps the panel identical on
// every route, numbered by the store's consecutive row ids.
interface DiagnosticLogEntry {
  id: number;
  source: 'app';
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
const COPY_LIMIT = 50;

// How many of the newest records the panel fetches and shows.
const PANEL_LIMIT = 100;

// Shape of the `cosci-diagnostic-event` CustomEvent's `detail`, as dispatched
// by callers elsewhere in the app (e.g. useChatSession's emitDiagnosticEvent)
// to surface a diagnostic line without those callers depending on this
// component directly.
interface DiagnosticLogEventDetail {
  run?: string;
  stage: string;
  level?: DiagnosticLogLevel;
  payload?: Record<string, unknown>;
}

// Sizing/positioning for the logs popover: capped to the viewport (dvh) with
// a narrower width override under the 720px breakpoint. The `!` overrides
// beat the shared .ucs-popover defaults applied by the parent's ShellPopover.
const LOGS_POPOVER_CLASSES = joinClasses(
  'ucs-popover--logs',
  'top-[calc(100%+0.45rem)] right-0 !w-[min(32rem,calc(100vw-2rem))]',
  'max-h-[min(32rem,calc(100dvh-6rem))] grid-rows-[auto_auto_minmax(0,1fr)]',
  '!gap-0 overflow-hidden !p-0 !border-cosci-logs-border ' +
    '!bg-cosci-logs-surface',
  'max-[720px]:right-[-0.5rem] max-[720px]:!w-[min(18.5rem,calc(100vw-1.5rem))]',
);

const LOGS_BUTTON_CLASSES =
  'ucs-logs-button relative inline-flex h-[2.35rem] min-w-max cursor-pointer ' +
  'items-center gap-[0.45rem] rounded-full border-0 ' +
  'bg-cosci-logs-accent-bg px-[0.62rem] py-0 pl-[0.72rem] ' +
  'font-[inherit] text-[0.88rem] font-semibold whitespace-nowrap ' +
  'text-cosci-logs-accent-fg hover:bg-cosci-logs-accent-hover ' +
  '[&[aria-expanded=true]]:bg-cosci-logs-accent-hover';

const LOGS_BUTTON_ICON_CLASSES = 'text-[1.05rem]';

const LOGS_COUNT_CLASSES =
  'ucs-logs-count grid h-[1.38rem] min-w-[1.35rem] place-items-center ' +
  'rounded-full bg-cosci-logs-count-bg px-[0.42rem] text-[0.72rem] ' +
  'leading-none whitespace-nowrap';

const DIAGNOSTIC_HEADER_CLASSES =
  'ucs-diagnostic-header flex items-center justify-between gap-3 border-b ' +
  'border-cosci-logs-border px-4 py-3 ' +
  'max-[720px]:flex-col max-[720px]:items-start';

const DIAGNOSTIC_INTRO_CLASSES =
  'ucs-diagnostic-intro border-b border-cosci-logs-border px-4 py-3';

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
  'focus-visible:bg-cosci-logs-action-hover';

const DIAGNOSTIC_CHIPS_CLASSES =
  'ucs-diagnostic-chips flex flex-wrap gap-[0.45rem]';

const DIAGNOSTIC_CHIP_CLASSES =
  'rounded-full bg-cosci-logs-accent-bg px-2 py-[0.15rem] ' +
  'text-[0.7rem] font-semibold whitespace-nowrap ' +
  'text-cosci-logs-accent-fg';

const DIAGNOSTIC_ERROR_CHIP_CLASSES =
  'rounded-full bg-cosci-logs-danger-bg px-2 py-[0.15rem] ' +
  'text-[0.7rem] font-semibold whitespace-nowrap ' +
  'text-cosci-logs-danger-fg';

const DIAGNOSTIC_LIST_CLASSES =
  'ucs-diagnostic-list grid min-h-0 gap-2 overflow-auto px-4 pt-3 pb-4';

const DIAGNOSTIC_ENTRY_CLASSES = 'ucs-diagnostic-entry grid gap-1';

const DIAGNOSTIC_ENTRY_META_CLASSES =
  'ucs-diagnostic-entry-meta grid ' +
  'grid-cols-[auto_auto_auto_minmax(0,1fr)_auto] ' +
  'items-center gap-2 text-[0.72rem] font-semibold ' +
  'text-cosci-logs-meta ' +
  'max-[720px]:grid-cols-[auto_auto_auto_minmax(0,1fr)]';

const DIAGNOSTIC_ENTRY_RUN_CLASSES = 'truncate';

const DIAGNOSTIC_ENTRY_STAGE_CLASSES =
  'max-[720px]:col-start-2 max-[720px]:col-end-[-1]';

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
function detailToClientRecord(
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
    ...(detail.run ? {run_id: detail.run} : {}),
  };
}

// WARNING and above read as errors; DEBUG/INFO as info. Backend records
// have no "success" notion.
function appLogLevel(record: AppLogRecord): DiagnosticLogLevel {
  return record.levelno >= 30 ? 'error' : 'info';
}

// Maps one persisted app_logs record into a rendered log entry. Records
// with no run id are attributed to the server itself.
function buildAppLogEntry(record: AppLogRecord): DiagnosticLogEntry {
  return {
    id: record.id,
    source: 'app',
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

// How often the open popover refreshes the persisted backend log.
const APP_LOGS_POLL_MS = 5_000;

// The fetched window plus the store's newest row id. The badge is
// numbered by `lastId` so it always agrees with the visible "#id" rows
// (row counts would drift, since ids survive a clear).
interface PersistedAppLogs {
  entries: DiagnosticLogEntry[];
  lastId: number;
}

// Fetches the app-wide persisted log: on mount (so the badge count is
// real), whenever `version` bumps (an in-page event or Clear changed the
// store), and on a poll while the popover is open. The same fetch runs on
// every route, so navigating never changes what the panel shows.
function usePersistedAppLogs(open: boolean, version: number): PersistedAppLogs {
  const [logs, setLogs] = useState<PersistedAppLogs>({
    entries: [],
    lastId: 0,
  });

  useEffect(() => {
    let disposed = false;
    const load = () => {
      getAppLogs(0, PANEL_LIMIT)
        .then(payload => {
          if (disposed) return;
          setLogs({
            entries: payload.logs.map(buildAppLogEntry),
            lastId: payload.last_id,
          });
        })
        .catch(() => {
          if (!disposed) setLogs({entries: [], lastId: 0});
        });
    };
    load();
    if (!open)
      return () => {
        disposed = true;
      };
    const timer = window.setInterval(load, APP_LOGS_POLL_MS);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [open, version]);

  return logs;
}

// Header "Logs" trigger button: shows the running entry count as a badge
// and toggles the popover open/closed. Purely presentational — all state
// lives in DiagnosticsControl.
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
    <button
      type="button"
      className={tooltipClassNames({
        className: LOGS_BUTTON_CLASSES,
        placement: 'left',
      })}
      aria-label={`Logs ${count}`}
      data-tooltip="Logs"
      aria-expanded={open}
      onClick={onToggle}
    >
      <Icon
        aria-hidden="true"
        className={LOGS_BUTTON_ICON_CLASSES}
        name="expand_more"
      />
      <span>Logs</span>
      <span className={LOGS_COUNT_CLASSES}>{count}</span>
    </button>
  );
}

// Ships `cosci-diagnostic-event` CustomEvents dispatched anywhere in the
// app to the persisted log, then notifies the caller so the list can
// refresh. Subscribed for the component's whole lifetime (not only while
// the popover is open) so no event is lost.
function useDiagnosticIngest(onIngested: () => void) {
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
function useNavigationLog(onIngested: () => void) {
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

// Per-level entry tallies plus the number of distinct runs represented, for
// the summary chips in DiagnosticLogsPanel.
interface DiagnosticCounts {
  errorCount: number;
  successCount: number;
  infoCount: number;
  runCount: number;
}

function summarizeDiagnosticEntries(
  entries: DiagnosticLogEntry[],
): DiagnosticCounts {
  return {
    errorCount: entries.filter(entry => entry.level === 'error').length,
    successCount: entries.filter(entry => entry.level === 'success').length,
    infoCount: entries.filter(entry => entry.level === 'info').length,
    runCount: new Set(entries.map(({run}) => run).filter(Boolean)).size,
  };
}

/**
 * Header "Logs" button plus its diagnostics popover.
 *
 * The panel renders the persisted app-wide log — the same list on every
 * route, numbered by the store's consecutive ids. In-page diagnostic
 * events and route navigations are shipped to that log via the ingestion
 * endpoint, Clear deletes the persisted log (server-side), and Copy
 * serializes only the newest {@link COPY_LIMIT} entries.
 *
 * @param props.open Whether the popover is shown; owned by the parent shell
 *   so it stays mutually exclusive with the Settings popover.
 * @param props.onToggle Requests the parent flip `open`.
 * @param props.renderPopover Lets the parent wrap the panel content in its
 *   own positioned popover container (shared with the Settings menu).
 */
export function DiagnosticsControl({
  open,
  onToggle,
  renderPopover,
}: {
  open: boolean;
  onToggle: () => void;
  renderPopover: (children: ReactNode, className: string) => ReactNode;
}) {
  // Bumped whenever the persisted log changed (ingest, navigation, clear)
  // so the fetch effect re-runs immediately instead of waiting for a poll.
  const [version, setVersion] = useState(0);
  const bumpVersion = () => setVersion(current => current + 1);
  const [copied, setCopied] = useState(false); // Copy button shows "Copied"
  useDiagnosticIngest(bumpVersion);
  useNavigationLog(bumpVersion);
  const {entries, lastId} = usePersistedAppLogs(open, version);
  const counts = summarizeDiagnosticEntries(entries);

  async function onCopy() {
    await copyText(JSON.stringify(entries.slice(-COPY_LIMIT), null, 2));
    setCopied(true);
  }

  async function onClear() {
    try {
      await deleteAppLogs();
    } catch {
      // Unreachable API: leave the list as-is; the next poll re-syncs.
    }
    setCopied(false);
    bumpVersion();
  }

  return (
    <>
      <LogsTriggerButton open={open} count={lastId} onToggle={onToggle} />
      {open &&
        renderPopover(
          <DiagnosticLogsPanel
            entries={entries}
            lastId={lastId}
            copied={copied}
            counts={counts}
            onClear={() => void onClear()}
            onCopy={() => void onCopy()}
          />,
          LOGS_POPOVER_CLASSES,
        )}
    </>
  );
}

// How close to the bottom (px) still counts as "pinned to the newest
// entry" for auto-follow purposes.
const PIN_THRESHOLD_PX = 24;

// Scrolling list of log entries (each entry's id/time/run/stage meta row plus
// its JSON payload), or an empty-state message when there are none.
function DiagnosticLogList({entries}: {entries: DiagnosticLogEntry[]}) {
  // Opening the panel lands on the newest entry (the list mounts pinned).
  // After that, new records only auto-scroll while the user is still at
  // the bottom — scrolling up to read must never be interrupted. Keyed by
  // the newest id, not the count: at the window cap the count stops
  // changing while the ids keep advancing.
  const listRef = useRef<HTMLDivElement>(null);
  const pinnedRef = useRef(true);
  const newestId = entries.length ? entries[entries.length - 1].id : 0;
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

  return (
    <div
      ref={listRef}
      onScroll={onScroll}
      className={DIAGNOSTIC_LIST_CLASSES}
      aria-label="Log events"
    >
      {entries.map(entry => (
        <article
          key={`${entry.source}-${entry.id}`}
          className={DIAGNOSTIC_ENTRY_CLASSES}
        >
          <div className={DIAGNOSTIC_ENTRY_META_CLASSES}>
            <span>#{entry.id}</span>
            <span>[{entry.time}]</span>
            <span>{entry.levelName}</span>
            <span className={DIAGNOSTIC_ENTRY_RUN_CLASSES}>{entry.run}</span>
            <strong className={DIAGNOSTIC_ENTRY_STAGE_CLASSES}>
              {entry.stage}:
            </strong>
          </div>
          <pre className={DIAGNOSTIC_CODE_CLASSES}>
            {entry.excText
              ? `${entry.message}\n\n${entry.excText}`
              : entry.message}
          </pre>
        </article>
      ))}
      {entries.length === 0 && (
        <p className={DIAGNOSTIC_EMPTY_CLASSES}>No diagnostic events loaded.</p>
      )}
    </div>
  );
}

// One Clear/Copy button in the header's actions row.
function DiagnosticActionButton({
  icon,
  label,
  onClick,
}: {
  icon: IconName;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={DIAGNOSTIC_ACTION_BUTTON_CLASSES}
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
}

// Popover header: the "Diagnostic Logs" title plus the Clear/Copy actions.
function DiagnosticLogsHeader({
  copied,
  onClear,
  onCopy,
}: {
  copied: boolean;
  onClear: () => void;
  onCopy: () => void;
}) {
  const actions: DiagnosticAction[] = [
    {id: 'clear', icon: 'refresh', label: 'Clear', onClick: onClear},
    {
      id: 'copy',
      icon: 'content_copy',
      label: copied ? 'Copied' : 'Copy',
      onClick: onCopy,
    },
  ];

  return (
    <div className={DIAGNOSTIC_HEADER_CLASSES}>
      <div className="ucs-diagnostic-title">
        <h2 className={DIAGNOSTIC_TITLE_CLASSES}>Diagnostic Logs</h2>
      </div>
      <div className={DIAGNOSTIC_ACTIONS_CLASSES}>
        {actions.map(({id, icon, label, onClick}) => (
          <DiagnosticActionButton
            key={id}
            icon={icon}
            label={label}
            onClick={onClick}
          />
        ))}
      </div>
    </div>
  );
}

// [label, count, chip class] rows for the summary chips; the Errors chip
// switches to the danger styling only when there is at least one error.
// The Total chip shows the newest log id (matching the badge and the
// visible "#id" rows); the per-level chips tally the shown window.
function buildDiagnosticChips(
  lastId: number,
  counts: DiagnosticCounts,
): [string, number, string][] {
  return [
    ['Total', lastId, DIAGNOSTIC_CHIP_CLASSES],
    [
      'Errors',
      counts.errorCount,
      counts.errorCount
        ? DIAGNOSTIC_ERROR_CHIP_CLASSES
        : DIAGNOSTIC_CHIP_CLASSES,
    ],
    ['Success', counts.successCount, DIAGNOSTIC_CHIP_CLASSES],
    ['Info', counts.infoCount, DIAGNOSTIC_CHIP_CLASSES],
    ['Runs', counts.runCount, DIAGNOSTIC_CHIP_CLASSES],
  ];
}

// Presentational body of the popover: the header (title + Clear/Copy
// actions), summary count chips, and the scrolling entry list. All state
// stays in DiagnosticsControl; this only renders what it is handed.
function DiagnosticLogsPanel({
  entries,
  lastId,
  copied,
  counts,
  onClear,
  onCopy,
}: {
  entries: DiagnosticLogEntry[];
  lastId: number;
  copied: boolean;
  counts: DiagnosticCounts;
  onClear: () => void;
  onCopy: () => void;
}) {
  const chips = buildDiagnosticChips(lastId, counts);

  return (
    <>
      <DiagnosticLogsHeader copied={copied} onClear={onClear} onCopy={onCopy} />
      <div className={DIAGNOSTIC_INTRO_CLASSES}>
        <div className={DIAGNOSTIC_CHIPS_CLASSES}>
          {chips.map(([label, count, className]) => (
            <span key={label} className={className}>
              {label} {count}
            </span>
          ))}
        </div>
      </div>
      <DiagnosticLogList entries={entries} />
    </>
  );
}
