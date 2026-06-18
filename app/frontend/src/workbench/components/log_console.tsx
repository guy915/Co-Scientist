import '@material/web/icon/icon.js';
import '@material/web/button/outlined-button.js';
import '@material/web/button/filled-tonal-button.js';
import {useCallback, useEffect, useRef, useState} from 'react';
import {useIsMobile} from '@/hooks/use_media_query';
import {useLogs, type LogEntry} from '../log_context';

function fmtTime(ts: number) {
  return new Date(ts * 1000).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
  });
}

function eventLabel(type: string): string {
  if (type === 'status') return 'STATUS';
  if (type === 'report') return 'REPORT';
  if (type.startsWith('engine.')) return `NODE: ${type.slice(7).toUpperCase()}`;
  return type.toUpperCase();
}

function eventLabelColor(type: string): string {
  if (type === 'status') return '#0969da';
  if (type === 'report') return '#1a7f37';
  if (type.startsWith('engine.')) return '#8250df';
  return '#953800';
}

function logText(entries: LogEntry[]): string {
  return entries
    .map((ev, i) => {
      const payload = JSON.stringify(ev.payload, null, 2);
      const label = eventLabel(ev.type);
      return `#${i + 1} [${fmtTime(ev.created_at)}] [${ev.run_label}] ${label}:\n${payload}`;
    })
    .join('\n\n');
}

/**
 * Renders a toggleable panel showing the app-wide diagnostic event log across
 * all runs known to the current session.
 */
export function LogConsole() {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLDivElement>(null);
  const isMobile = useIsMobile();

  const {entries, loading, refresh} = useLogs();
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom whenever new entries arrive or panel opens
  useEffect(() => {
    if (!open) return;
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [open, entries]);

  // Reload when the panel opens
  useEffect(() => {
    if (open) void refresh();
  }, [open, refresh]);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (
        panelRef.current &&
        !panelRef.current.contains(e.target as Node) &&
        buttonRef.current &&
        !buttonRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open]);

  const handleCopy = useCallback(async () => {
    await navigator.clipboard.writeText(
      entries.length ? logText(entries) : '(no events)',
    );
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [entries]);

  return (
    <div className="relative">
      <div
        ref={buttonRef}
        className="relative"
        style={{display: 'inline-flex'}}
      >
        <md-filled-tonal-button
          onclick={(() => setOpen((v) => !v)) as EventListener}
          aria-expanded={open}
          aria-label="Toggle log console"
        >
          Logs
          {entries.length > 0 && (
            <span
              className="inline-flex items-center justify-center rounded-full text-xs font-bold w-5 h-5 ml-1.5"
              style={{backgroundColor: 'rgba(255,255,255,0.25)'}}
            >
              {entries.length}
            </span>
          )}
          <md-icon slot="icon" aria-hidden="true">
            {open ? 'expand_less' : 'expand_more'}
          </md-icon>
        </md-filled-tonal-button>
      </div>

      {open && (
        <>
          {/* Mobile: semi-transparent backdrop */}
          {isMobile && (
            <div
              className="fixed inset-0 z-40"
              style={{backgroundColor: 'rgba(0,0,0,0.35)'}}
              onClick={() => setOpen(false)}
            />
          )}
          <div
            ref={panelRef}
            className="z-50 rounded-lg shadow-xl overflow-hidden"
            style={{
              ...(isMobile
                ? {
                    position: 'fixed',
                    top: '64px',
                    left: '0',
                    right: '0',
                    maxHeight: 'calc(100dvh - 80px)',
                  }
                : {
                    position: 'absolute',
                    top: 'calc(100% + 12px)',
                    right: '0',
                    width: 'min(600px, calc(100vw - 2rem))',
                    maxHeight: '520px',
                  }),
              border: '1px solid var(--md-sys-color-outline-variant)',
              backgroundColor: 'var(--color-th-card)',
              display: 'flex',
              flexDirection: 'column',
            }}
          >
            {/* Panel header */}
            <div
              className="flex items-center justify-between px-4 py-3 border-b shrink-0"
              style={{borderColor: 'var(--md-sys-color-outline-variant)'}}
            >
              <div className="flex items-center gap-2">
                <span className="font-semibold text-base">Diagnostic Logs</span>
                <span
                  className="text-xs px-2 py-0.5 rounded-full"
                  style={{
                    backgroundColor: 'var(--md-sys-color-secondary-container)',
                    color: 'var(--md-sys-color-on-secondary-container)',
                  }}
                >
                  All runs
                </span>
              </div>
              <div className="flex items-center gap-2">
                {loading && (
                  <span
                    className="text-xs"
                    style={{color: 'var(--md-sys-color-on-surface-variant)'}}
                  >
                    loading…
                  </span>
                )}
                <md-outlined-button
                  onclick={(() => void refresh()) as EventListener}
                  aria-label="Refresh logs"
                >
                  <md-icon slot="icon" aria-hidden="true">
                    refresh
                  </md-icon>
                  Refresh
                </md-outlined-button>
                <md-outlined-button
                  onclick={(() => void handleCopy()) as EventListener}
                  disabled={!entries.length || undefined}
                >
                  <md-icon slot="icon" aria-hidden="true">
                    {copied ? 'check' : 'content_copy'}
                  </md-icon>
                  {copied ? 'Copied!' : 'Copy'}
                </md-outlined-button>
              </div>
            </div>

            {/* Log body */}
            <div
              ref={scrollRef}
              className="flex-1 overflow-y-auto px-4 py-3 space-y-4 text-sm"
              style={{fontFamily: 'ui-monospace, monospace'}}
            >
              {!loading && entries.length === 0 && (
                <p
                  className="text-sm"
                  style={{
                    color: 'var(--md-sys-color-on-surface-variant)',
                    fontFamily: 'sans-serif',
                  }}
                >
                  No events recorded yet. Start a run to see diagnostic events
                  here.
                </p>
              )}
              {entries.map((ev: LogEntry, i: number) => (
                <div key={`${ev.run_id}-${ev.seq}`}>
                  <div className="flex items-baseline gap-2 mb-1 flex-wrap">
                    <span
                      className="text-xs font-bold"
                      style={{
                        color: 'var(--md-sys-color-on-surface-variant)',
                        minWidth: '2rem',
                      }}
                    >
                      #{i + 1}
                    </span>
                    <span
                      className="text-xs"
                      style={{color: 'var(--md-sys-color-on-surface-variant)'}}
                    >
                      [{fmtTime(ev.created_at)}]
                    </span>
                    <span
                      className="text-xs px-1.5 py-0.5 rounded"
                      style={{
                        backgroundColor:
                          'var(--md-sys-color-surface-container-high)',
                        color: 'var(--md-sys-color-on-surface-variant)',
                        maxWidth: '180px',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                        display: 'inline-block',
                      }}
                      title={ev.run_label}
                    >
                      {ev.run_label}
                    </span>
                    <span
                      className="text-xs font-bold"
                      style={{color: eventLabelColor(ev.type)}}
                    >
                      {eventLabel(ev.type)}:
                    </span>
                  </div>
                  <pre
                    className="ml-10 text-xs whitespace-pre-wrap break-all rounded px-3 py-2"
                    style={{
                      backgroundColor:
                        'var(--md-sys-color-secondary-container)',
                      color: 'var(--md-sys-color-on-surface)',
                      lineHeight: '1.6',
                    }}
                  >
                    {JSON.stringify(ev.payload, null, 2)}
                  </pre>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
