import {useEffect, useRef, useState, type ReactNode} from 'react';
import {getRunEvents, type RunEvent} from '@/api/runs';
import {Icon, type IconName} from '@/components/icon';
import {copyText} from '@/lib/clipboard';
import {DIAGNOSTIC_EVENT} from './dom_events';
import {tooltipClassNames} from './tooltip';

type DiagnosticLogLevel = 'info' | 'success' | 'error';

// One rendered row in the Logs panel; assigned a local monotonic id and
// formatted timestamp when the underlying event is received (see the
// `cosci-diagnostic-event` listener in DiagnosticsControl below). Entries
// come from two sources: ephemeral session events dispatched in-page, and
// the active run's persisted event log fetched from the API; `source`
// disambiguates them for stable list keys.
interface DiagnosticLogEntry {
  id: number;
  source: 'session' | 'run';
  time: string;
  run: string;
  stage: string;
  level: DiagnosticLogLevel;
  payload: Record<string, unknown>;
}

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
const LOGS_POPOVER_CLASSES = [
  'ucs-popover--logs',
  'top-[calc(100%+0.45rem)] right-0 !w-[min(32rem,calc(100vw-2rem))]',
  'max-h-[min(32rem,calc(100dvh-6rem))] grid-rows-[auto_auto_minmax(0,1fr)]',
  '!gap-0 overflow-hidden !p-0 !border-cosci-logs-border ' +
    '!bg-cosci-logs-surface',
  'max-[720px]:right-[-0.5rem] max-[720px]:!w-[min(18.5rem,calc(100vw-1.5rem))]',
].join(' ');

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
  'ucs-diagnostic-entry-meta grid grid-cols-[auto_auto_minmax(0,1fr)_auto] ' +
  'items-center gap-2 text-[0.72rem] font-semibold ' +
  'text-cosci-logs-meta ' +
  'max-[720px]:grid-cols-[auto_auto_minmax(0,1fr)]';

const DIAGNOSTIC_ENTRY_RUN_CLASSES = 'truncate';

const DIAGNOSTIC_ENTRY_STAGE_CLASSES =
  'max-[720px]:col-start-2 max-[720px]:col-end-[-1]';

const DIAGNOSTIC_CODE_CLASSES =
  'm-0 max-h-20 overflow-auto rounded-[0.55rem] ' +
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

// Builds a log entry from a raw diagnostic-event detail, filling in the
// per-field defaults (run/level/payload) the dispatched CustomEvent may omit.
function buildDiagnosticEntry(
  id: number,
  detail: DiagnosticLogEventDetail,
): DiagnosticLogEntry {
  return {
    id,
    source: 'session',
    time: formatDiagnosticTime(),
    run: detail.run || 'Current session',
    stage: detail.stage,
    level: detail.level || 'info',
    payload: detail.payload || {},
  };
}

// Level for a persisted run event: terminal failures and blocks read as
// errors, publication/completion as success, everything else as info.
function persistedEventLevel(event: RunEvent): DiagnosticLogLevel {
  const status = event.payload['status'];
  if (status === 'failed' || status === 'blocked') return 'error';
  if (event.type === 'report' || status === 'completed') return 'success';
  return 'info';
}

// Maps one persisted run_events row into a rendered log entry. The run
// column shows the short run id (matching how the backend logs it).
function buildPersistedEntry(
  runId: string,
  event: RunEvent,
): DiagnosticLogEntry {
  return {
    id: event.seq,
    source: 'run',
    time: formatDiagnosticTime(new Date(event.created_at * 1000)),
    run: `Run ${runId.slice(0, 8)}`,
    stage: event.type,
    level: persistedEventLevel(event),
    payload: event.payload,
  };
}

// Fetches the active run's persisted event log each time the popover opens,
// so reloads (which lose the ephemeral session log) still show the run's
// durable timeline. No run in scope (home routes) yields an empty list.
function usePersistedRunEvents(
  runId: string | undefined,
  open: boolean,
): DiagnosticLogEntry[] {
  const [entries, setEntries] = useState<DiagnosticLogEntry[]>([]);

  useEffect(() => {
    if (!runId) {
      setEntries([]);
      return;
    }
    if (!open) return;
    let disposed = false;
    getRunEvents(runId)
      .then(events => {
        if (disposed) return;
        setEntries(events.map(event => buildPersistedEntry(runId, event)));
      })
      .catch(() => {
        if (!disposed) setEntries([]);
      });
    return () => {
      disposed = true;
    };
  }, [runId, open]);

  return entries;
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

// Accumulates `cosci-diagnostic-event` CustomEvents dispatched anywhere in
// the app into an in-memory (non-persisted) log for local debugging, plus
// the Clear/Copy actions and the "Copied" confirmation flag.
function useDiagnosticLog() {
  const [entries, setEntries] = useState<DiagnosticLogEntry[]>([]);
  const [copied, setCopied] = useState(false); // Copy button shows "Copied"
  // Monotonic id source for entries; a ref (not state) because it is only
  // read/written imperatively and must not itself trigger re-renders.
  const nextEntryId = useRef(1);

  function clearLogs() {
    nextEntryId.current = 1;
    setEntries([]);
    setCopied(false);
  }

  // Takes the full displayed list (persisted + session) so Copy captures
  // exactly what the panel shows, not just this hook's session entries.
  async function copyLogs(displayed: DiagnosticLogEntry[]) {
    await copyText(JSON.stringify(displayed, null, 2));
    setCopied(true);
  }

  // Subscribed for the component's whole lifetime (no deps) rather than only
  // while the popover is open, so events fired while it is closed still land
  // in the log and the trigger's count badge stays accurate.
  useEffect(() => {
    function onDiagnosticEvent(event: Event) {
      const custom = event as CustomEvent<DiagnosticLogEventDetail>;
      if (!custom.detail?.stage) return; // ignore malformed events
      const entry = buildDiagnosticEntry(nextEntryId.current, custom.detail);
      nextEntryId.current += 1;
      setEntries(current => [...current, entry]);
      setCopied(false); // new entries invalidate a prior "Copied" confirmation
    }
    window.addEventListener(DIAGNOSTIC_EVENT, onDiagnosticEvent);
    return () => {
      window.removeEventListener(DIAGNOSTIC_EVENT, onDiagnosticEvent);
    };
  }, []);

  return {entries, copied, clearLogs, copyLogs};
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
 * The panel shows the active run's persisted event log (fetched from the
 * API whenever the popover opens, so it survives reloads) ahead of the
 * ephemeral session events dispatched in-page. Clear only drops the
 * session entries; the persisted timeline is the store's, not ours.
 *
 * @param props.open Whether the popover is shown; owned by the parent shell
 *   so it stays mutually exclusive with the Settings popover.
 * @param props.onToggle Requests the parent flip `open`.
 * @param props.runId The active run route's id, if any; enables the
 *   persisted-event section.
 * @param props.renderPopover Lets the parent wrap the panel content in its
 *   own positioned popover container (shared with the Settings menu).
 */
export function DiagnosticsControl({
  open,
  onToggle,
  runId,
  renderPopover,
}: {
  open: boolean;
  onToggle: () => void;
  runId?: string;
  renderPopover: (children: ReactNode, className: string) => ReactNode;
}) {
  const {entries, copied, clearLogs, copyLogs} = useDiagnosticLog();
  const persisted = usePersistedRunEvents(runId, open);
  // Persisted history first (it predates this session), then live entries.
  const combined = [...persisted, ...entries];
  const counts = summarizeDiagnosticEntries(combined);

  return (
    <>
      <LogsTriggerButton
        open={open}
        count={combined.length}
        onToggle={onToggle}
      />
      {open &&
        renderPopover(
          <DiagnosticLogsPanel
            entries={combined}
            copied={copied}
            counts={counts}
            onClear={clearLogs}
            onCopy={() => void copyLogs(combined)}
          />,
          LOGS_POPOVER_CLASSES,
        )}
    </>
  );
}

// Scrolling list of log entries (each entry's id/time/run/stage meta row plus
// its JSON payload), or an empty-state message when there are none.
function DiagnosticLogList({entries}: {entries: DiagnosticLogEntry[]}) {
  return (
    <div className={DIAGNOSTIC_LIST_CLASSES} aria-label="Log events">
      {entries.map(entry => (
        <article
          key={`${entry.source}-${entry.id}`}
          className={DIAGNOSTIC_ENTRY_CLASSES}
        >
          <div className={DIAGNOSTIC_ENTRY_META_CLASSES}>
            <span>#{entry.id}</span>
            <span>[{entry.time}]</span>
            <span className={DIAGNOSTIC_ENTRY_RUN_CLASSES}>{entry.run}</span>
            <strong className={DIAGNOSTIC_ENTRY_STAGE_CLASSES}>
              {entry.stage}:
            </strong>
          </div>
          <pre className={DIAGNOSTIC_CODE_CLASSES}>
            {JSON.stringify(entry.payload, null, 2)}
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
function buildDiagnosticChips(
  entryCount: number,
  counts: DiagnosticCounts,
): [string, number, string][] {
  return [
    ['Total', entryCount, DIAGNOSTIC_CHIP_CLASSES],
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
  copied,
  counts,
  onClear,
  onCopy,
}: {
  entries: DiagnosticLogEntry[];
  copied: boolean;
  counts: DiagnosticCounts;
  onClear: () => void;
  onCopy: () => void;
}) {
  const chips = buildDiagnosticChips(entries.length, counts);

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
