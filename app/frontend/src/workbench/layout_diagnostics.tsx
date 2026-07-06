import {useEffect, useRef, useState, type ReactNode} from 'react';
import {Icon} from '@/components/icon';
import {tooltipClassNames} from './tooltip';

type DiagnosticLogLevel = 'info' | 'success' | 'error';

interface DiagnosticLogEntry {
  id: number;
  time: string;
  run: string;
  stage: string;
  level: DiagnosticLogLevel;
  payload: Record<string, unknown>;
}

interface DiagnosticLogEventDetail {
  run?: string;
  stage: string;
  level?: DiagnosticLogLevel;
  payload?: Record<string, unknown>;
}

const LOGS_POPOVER_CLASSES = [
  'ucs-popover--logs',
  'top-[calc(100%+0.45rem)] right-0 !w-[min(32rem,calc(100vw-2rem))]',
  'max-h-[min(32rem,calc(100vh-6rem))] grid-rows-[auto_auto_minmax(0,1fr)]',
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

function formatDiagnosticTime(date = new Date()): string {
  return new Intl.DateTimeFormat(undefined, {
    hour: 'numeric',
    minute: '2-digit',
    second: '2-digit',
  }).format(date);
}

export function DiagnosticsControl({
  open,
  onToggle,
  renderPopover,
}: {
  open: boolean;
  onToggle: () => void;
  renderPopover: (children: ReactNode, className: string) => ReactNode;
}) {
  const [entries, setEntries] = useState<DiagnosticLogEntry[]>([]);
  const [copied, setCopied] = useState(false);
  const nextEntryId = useRef(1);
  const errorCount = entries.filter(entry => entry.level === 'error').length;
  const successCount = entries.filter(
    entry => entry.level === 'success',
  ).length;
  const infoCount = entries.filter(entry => entry.level === 'info').length;
  const runCount = new Set(entries.map(({run}) => run).filter(Boolean)).size;

  function clearLogs() {
    nextEntryId.current = 1;
    setEntries([]);
    setCopied(false);
  }

  async function copyLogs() {
    const text = JSON.stringify(entries, null, 2);
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        throw new Error('Clipboard API unavailable');
      }
    } catch {
      const textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.setAttribute('readonly', '');
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.append(textarea);
      textarea.select();
      document.execCommand('copy');
      textarea.remove();
    }
    setCopied(true);
  }

  useEffect(() => {
    function onDiagnosticEvent(event: Event) {
      const custom = event as CustomEvent<DiagnosticLogEventDetail>;
      if (!custom.detail?.stage) return;
      const entry: DiagnosticLogEntry = {
        id: nextEntryId.current,
        time: formatDiagnosticTime(),
        run: custom.detail.run || 'Current session',
        stage: custom.detail.stage,
        level: custom.detail.level || 'info',
        payload: custom.detail.payload || {},
      };
      nextEntryId.current += 1;
      setEntries(current => [...current, entry]);
      setCopied(false);
    }
    window.addEventListener('cosci-diagnostic-event', onDiagnosticEvent);
    return () => {
      window.removeEventListener('cosci-diagnostic-event', onDiagnosticEvent);
    };
  }, []);

  return (
    <>
      <button
        type="button"
        className={tooltipClassNames({
          className: LOGS_BUTTON_CLASSES,
          placement: 'left',
        })}
        aria-label={`Logs ${entries.length}`}
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
        <span className={LOGS_COUNT_CLASSES}>{entries.length}</span>
      </button>
      {open &&
        renderPopover(
          <DiagnosticLogsPanel
            entries={entries}
            copied={copied}
            errorCount={errorCount}
            successCount={successCount}
            infoCount={infoCount}
            runCount={runCount}
            onClear={clearLogs}
            onCopy={copyLogs}
          />,
          LOGS_POPOVER_CLASSES,
        )}
    </>
  );
}

function DiagnosticLogsPanel({
  entries,
  copied,
  errorCount,
  successCount,
  infoCount,
  runCount,
  onClear,
  onCopy,
}: {
  entries: DiagnosticLogEntry[];
  copied: boolean;
  errorCount: number;
  successCount: number;
  infoCount: number;
  runCount: number;
  onClear: () => void;
  onCopy: () => void;
}) {
  const chips: Array<[string, number, string]> = [
    ['Total', entries.length, DIAGNOSTIC_CHIP_CLASSES],
    [
      'Errors',
      errorCount,
      errorCount ? DIAGNOSTIC_ERROR_CHIP_CLASSES : DIAGNOSTIC_CHIP_CLASSES,
    ],
    ['Success', successCount, DIAGNOSTIC_CHIP_CLASSES],
    ['Info', infoCount, DIAGNOSTIC_CHIP_CLASSES],
    ['Runs', runCount, DIAGNOSTIC_CHIP_CLASSES],
  ];

  return (
    <>
      <div className={DIAGNOSTIC_HEADER_CLASSES}>
        <div className="ucs-diagnostic-title">
          <h2 className={DIAGNOSTIC_TITLE_CLASSES}>Diagnostic Logs</h2>
        </div>
        <div className={DIAGNOSTIC_ACTIONS_CLASSES}>
          <button
            type="button"
            className={DIAGNOSTIC_ACTION_BUTTON_CLASSES}
            onClick={onClear}
          >
            <Icon aria-hidden="true" className="text-base" name="refresh" />
            <span>Clear</span>
          </button>
          <button
            type="button"
            className={DIAGNOSTIC_ACTION_BUTTON_CLASSES}
            onClick={onCopy}
          >
            <Icon
              aria-hidden="true"
              className="text-base"
              name="content_copy"
            />
            <span>{copied ? 'Copied' : 'Copy'}</span>
          </button>
        </div>
      </div>
      <div className={DIAGNOSTIC_INTRO_CLASSES}>
        <div className={DIAGNOSTIC_CHIPS_CLASSES}>
          {chips.map(([label, count, className]) => (
            <span key={label} className={className}>
              {label} {count}
            </span>
          ))}
        </div>
      </div>
      <div className={DIAGNOSTIC_LIST_CLASSES} aria-label="Log events">
        {entries.map(entry => (
          <article key={entry.id} className={DIAGNOSTIC_ENTRY_CLASSES}>
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
          <p className={DIAGNOSTIC_EMPTY_CLASSES}>
            No diagnostic events loaded.
          </p>
        )}
      </div>
    </>
  );
}
