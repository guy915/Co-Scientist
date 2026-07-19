import {useEffect, useRef, useState, type ReactNode} from 'react';
import {useLocation} from 'react-router-dom';
import {
  APP_LOGS_CHANGED_EVENT,
  deleteAppLogs,
  getAppLogs,
  postAppLogs,
} from '@/api/logs';
import {Icon, type IconName} from '@/components/icon';
import {copyText} from '@/lib/clipboard';
import {joinClasses} from './classes';
import {DIAGNOSTIC_EVENT} from './dom_events';
import {
  APP_LOGS_POLL_MS,
  buildAppLogEntry,
  COPY_LIMIT,
  detailToClientRecord,
  PANEL_LIMIT,
  summarizeDiagnosticEntries,
  type DiagnosticCounts,
  type DiagnosticLogEntry,
  type DiagnosticLogEventDetail,
  type PersistedAppLogs,
} from './layout_diagnostics_data';
import {tooltipClassNames} from './tooltip';

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

// Fetches the app-wide persisted log: on mount (so the badge count is
// real), whenever `version` bumps (Clear changed the store), whenever
// the api layer announces a change (a click or error was just
// persisted), and on a steady background poll — popover open or not, so
// the badge never depends on opening the panel. The same fetch runs on
// every route, so navigating never changes what the panel shows.
function usePersistedAppLogs(version: number): PersistedAppLogs {
  const [logs, setLogs] = useState<PersistedAppLogs>({
    entries: [],
    total: 0,
  });

  useEffect(() => {
    let disposed = false;
    // Requests can resolve out of order (an announce-triggered load can
    // race the poll); only the most recently issued request may apply.
    let latestRequest = 0;
    const load = () => {
      const request = ++latestRequest;
      getAppLogs(0, PANEL_LIMIT)
        .then(payload => {
          if (disposed || request !== latestRequest) return;
          // The request already asks for PANEL_LIMIT records, but the
          // cap is enforced here too: whatever the payload size, the
          // panel shows at most the newest PANEL_LIMIT.
          const shown = payload.logs.slice(-PANEL_LIMIT);
          // Number backwards from the stream total so the newest row is
          // always `total`: a capped window shows 151..250, not 1..100.
          const total = Math.max(payload.total, shown.length);
          const first = total - shown.length + 1;
          setLogs({
            entries: shown.map((record, index) =>
              buildAppLogEntry(record, first + index),
            ),
            total,
          });
        })
        .catch(() => {
          if (!disposed && request === latestRequest)
            setLogs({entries: [], total: 0});
        });
    };
    load();
    const timer = window.setInterval(load, APP_LOGS_POLL_MS);
    window.addEventListener(APP_LOGS_CHANGED_EVENT, load);
    return () => {
      disposed = true;
      window.clearInterval(timer);
      window.removeEventListener(APP_LOGS_CHANGED_EVENT, load);
    };
  }, [version]);

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
  const {entries, total} = usePersistedAppLogs(version);
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
      <LogsTriggerButton open={open} count={total} onToggle={onToggle} />
      {open &&
        renderPopover(
          <DiagnosticLogsPanel
            entries={entries}
            total={total}
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
            <span>#{entry.number}</span>
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
// The Total chip is the size of the filtered stream, which is also the
// newest row's number; the per-level chips tally the shown window.
function buildDiagnosticChips(
  total: number,
  counts: DiagnosticCounts,
): [string, number, string][] {
  return [
    ['Total', total, DIAGNOSTIC_CHIP_CLASSES],
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
  total,
  copied,
  counts,
  onClear,
  onCopy,
}: {
  entries: DiagnosticLogEntry[];
  total: number;
  copied: boolean;
  counts: DiagnosticCounts;
  onClear: () => void;
  onCopy: () => void;
}) {
  const chips = buildDiagnosticChips(total, counts);

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
