import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from 'react';
import {deleteAppLogs} from '@/api/logs';
import {Icon, type IconName} from '@/components/icon';
import {copyText} from '@/lib/clipboard';
import {joinClasses} from './classes';
import {
  COPY_LIMIT,
  summarizeDiagnosticEntries,
  type DiagnosticCounts,
  type DiagnosticLogEntry,
} from './layout_diagnostics_data';
import {
  useDiagnosticIngest,
  useNavigationLog,
  usePersistedAppLogs,
} from './layout_diagnostics_state';
import {headerControlButtonClasses} from './layout_primitives';
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
  'max-[720px]:right-[-0.5rem] ' +
    'max-[720px]:!w-[min(18.5rem,calc(100vw-1.5rem))]',
);

// The shared pill chrome, with the right side tightened around the badge.
const LOGS_BUTTON_CLASSES = headerControlButtonClasses(
  'px-[0.62rem] py-0 pl-[0.72rem]',
);

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
  'max-[720px]:grid-cols-[auto_auto_auto_minmax(0,1fr)]';

const DIAGNOSTIC_ENTRY_RUN_CLASSES = 'truncate';

const DIAGNOSTIC_ENTRY_STAGE_CLASSES =
  'min-w-0 truncate max-[720px]:col-start-2 max-[720px]:col-end-[-1]';

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
interface DiagnosticsControlProps {
  open: boolean;
  onToggle: () => void;
  renderPopover: (children: ReactNode, className: string) => ReactNode;
}

// Builds the Copy/Clear handlers for the popover: Copy serializes the
// newest COPY_LIMIT entries to the clipboard, Clear deletes the persisted
// log server-side. Both flip local UI state the caller owns.
function makeDiagnosticActions(
  entries: DiagnosticLogEntry[],
  setCopied: Dispatch<SetStateAction<boolean>>,
  bumpVersion: () => void,
) {
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

  return {onCopy, onClear};
}

export function DiagnosticsControl({
  open,
  onToggle,
  renderPopover,
}: DiagnosticsControlProps) {
  // Bumped whenever the persisted log changed (ingest, navigation, clear)
  // so the fetch effect re-runs immediately instead of waiting for a poll.
  const [version, setVersion] = useState(0);
  const bumpVersion = () => setVersion(current => current + 1);
  const [copied, setCopied] = useState(false); // Copy button shows "Copied"
  useDiagnosticIngest(bumpVersion);
  useNavigationLog(bumpVersion);
  const {entries, total} = usePersistedAppLogs(version, open);
  // Memoized on the entries array, which only changes when a load applies
  // — closed-state badge polls never pay for the tallies.
  const counts = useMemo(() => summarizeDiagnosticEntries(entries), [entries]);
  const {onCopy, onClear} = makeDiagnosticActions(
    entries,
    setCopied,
    bumpVersion,
  );

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
