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

function fmtDateTime(ts: number) {
  return new Date(ts * 1000).toLocaleString();
}

function eventLabel(type: string): string {
  if (type === 'status') return 'STATUS';
  if (type === 'report') return 'REPORT';
  if (type.startsWith('engine.')) return `NODE: ${type.slice(7).toUpperCase()}`;
  return type.toUpperCase();
}

type LogSeverity = 'ERROR' | 'SUCCESS' | 'INFO';

interface DiagnosticStats {
  total: number;
  errors: number;
  success: number;
  info: number;
  runs: number;
}

interface DiagnosticExportContext {
  currentUrl?: string;
  userAgent?: string;
  exportedAt?: Date;
}

function payloadString(
  payload: Record<string, unknown>,
  key: string,
): string | null {
  const value = payload[key];
  return typeof value === 'string' ? value.toLowerCase() : null;
}

function logSeverity(ev: LogEntry): LogSeverity {
  const type = ev.type.toLowerCase();
  const status = payloadString(ev.payload, 'status');
  const decision = payloadString(ev.payload, 'decision');

  if (
    type.includes('error') ||
    typeof ev.payload.error === 'string' ||
    status === 'failed' ||
    status === 'blocked' ||
    decision === 'block' ||
    decision === 'redact'
  ) {
    return 'ERROR';
  }

  if (
    type.includes('success') ||
    ev.type === 'report' ||
    status === 'completed'
  ) {
    return 'SUCCESS';
  }

  return 'INFO';
}

function severityColor(severity: LogSeverity): string {
  if (severity === 'ERROR') return 'var(--md-sys-color-error)';
  if (severity === 'SUCCESS') return 'var(--color-th-success)';
  return 'var(--md-sys-color-on-surface-variant)';
}

function eventLabelColor(type: string, severity: LogSeverity): string {
  if (severity !== 'INFO') return severityColor(severity);
  if (type === 'status') return 'var(--color-info)';
  if (type.startsWith('engine.')) return 'var(--md-sys-color-tertiary)';
  return 'var(--md-sys-color-primary)';
}

function diagnosticStats(entries: LogEntry[]): DiagnosticStats {
  const stats: DiagnosticStats = {
    total: entries.length,
    errors: 0,
    success: 0,
    info: 0,
    runs: new Set(entries.map(ev => ev.run_id)).size,
  };

  for (const ev of entries) {
    const severity = logSeverity(ev);
    if (severity === 'ERROR') stats.errors += 1;
    if (severity === 'SUCCESS') stats.success += 1;
    if (severity === 'INFO') stats.info += 1;
  }

  return stats;
}

export function formatDiagnosticLog(
  entries: LogEntry[],
  context: DiagnosticExportContext = {},
): string {
  const stats = diagnosticStats(entries);
  const exportedAt = context.exportedAt ?? new Date();
  const firstEvent = entries[0]?.created_at;
  const currentUrl = context.currentUrl ?? 'Unavailable';
  const userAgent = context.userAgent ?? 'Unavailable';

  const sections = [
    '=== ABOUT THESE DIAGNOSTIC LOGS ===',
    'This is the Co-Scientist workbench diagnostic log export. It captures persisted run events, lifecycle changes, engine stages, reports, safety decisions, and failures visible to this browser. These logs provide a timeline of what happened across your research runs, making it easier to troubleshoot issues and understand application behavior. If you encounter problems, share this full export when asking for help - it includes context that is useful for maintainers and coding agents.',
    '',
    '=== WHAT THIS TOOL TRACKS ===',
    'Run Lifecycle:',
    '- Run creation, queueing, startup, cancellation, completion, and failure states',
    '- Provider and run-mode changes stored in lifecycle events',
    '',
    'Engine Activity:',
    '- Supervisor, generation, reflection, ranking, evolution, review, and report events',
    '- Mock workflow and live engine events when available',
    '',
    'Research Outputs:',
    '- Hypothesis, evidence, citation-audit, tournament, and report milestones',
    '- Safety intake and final-output decisions',
    '',
    'Error Tracking:',
    '- Failed or blocked run statuses',
    '- Events that include error payloads or blocking safety decisions',
    '',
    '=== SESSION DETAILS ===',
    `Date: ${exportedAt.toLocaleString()}`,
    `First Loaded Event: ${firstEvent ? fmtDateTime(firstEvent) : 'No events loaded'}`,
    `Current URL: ${currentUrl}`,
    `Browser: ${userAgent}`,
    `Runs Covered: ${stats.runs}`,
    '',
    '=== STATISTICS ===',
    `Total Logs: ${stats.total}`,
    `Errors: ${stats.errors}`,
    `Success: ${stats.success}`,
    `Info: ${stats.info}`,
    '',
    '=== LEGEND ===',
    'ERROR   - Failures, blocked states, error payloads, or blocking safety decisions',
    'SUCCESS - Completed statuses, generated reports, or explicit success events',
    'INFO    - General run, engine, research, and lifecycle events',
    '',
    'Log Format: #EXPORT_ID [timestamp] TYPE: [run label] EVENT (run_id=..., seq=...)',
    '- EXPORT_ID: Sequential number within this export',
    '- seq: Persisted sequence number for that event within its run',
    '- Data: Additional event payload context in JSON format',
    '',
    '=== LOGS ===',
    entries.length
      ? entries
          .map((ev, i) => {
            const payload = JSON.stringify(ev.payload, null, 2);
            const label = eventLabel(ev.type);
            const severity = logSeverity(ev);
            return `#${i + 1} [${fmtTime(ev.created_at)}] ${severity}: [${ev.run_label}] ${label} (run_id=${ev.run_id}, seq=${ev.seq})\n${payload}`;
          })
          .join('\n\n')
      : '(no events)',
  ];

  return sections.join('\n');
}

function StatChip({
  label,
  value,
  tone = 'info',
}: {
  label: string;
  value: number;
  tone?: 'info' | 'success' | 'error';
}) {
  const colors = {
    info: {
      backgroundColor: 'var(--md-sys-color-secondary-container)',
      color: 'var(--md-sys-color-on-secondary-container)',
    },
    success: {
      backgroundColor: 'var(--color-th-success-container)',
      color: 'var(--color-th-on-success-container)',
    },
    error: {
      backgroundColor: 'var(--md-sys-color-error-container)',
      color: 'var(--md-sys-color-on-error-container)',
    },
  }[tone];

  return (
    <span
      className="inline-flex items-center gap-1 rounded-full px-2 py-1 text-xs font-semibold"
      style={colors}
    >
      <span>{label}</span>
      <span>{value}</span>
    </span>
  );
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
  const stats = diagnosticStats(entries);

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
      formatDiagnosticLog(entries, {
        currentUrl:
          typeof window === 'undefined' ? undefined : window.location.href,
        userAgent:
          typeof window === 'undefined'
            ? undefined
            : window.navigator.userAgent,
      }),
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
          onclick={(() => setOpen(v => !v)) as EventListener}
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
                  aria-label="Copy all diagnostic logs"
                >
                  <md-icon slot="icon" aria-hidden="true">
                    {copied ? 'check' : 'content_copy'}
                  </md-icon>
                  {copied ? 'Copied!' : 'Copy all'}
                </md-outlined-button>
              </div>
            </div>

            <div
              className="px-4 py-3 border-b"
              style={{
                borderColor: 'var(--md-sys-color-outline-variant)',
                backgroundColor: 'var(--md-sys-color-surface-container-low)',
              }}
            >
              <p
                className="text-xs leading-5 mb-3"
                style={{color: 'var(--md-sys-color-on-surface-variant)'}}
              >
                Export includes all loaded run events, agent-stage updates,
                reports, safety decisions, and failure context. Share the copied
                text when troubleshooting so the full timeline is available.
              </p>
              <div className="flex flex-wrap gap-2">
                <StatChip label="Total" value={stats.total} />
                <StatChip label="Errors" value={stats.errors} tone="error" />
                <StatChip
                  label="Success"
                  value={stats.success}
                  tone="success"
                />
                <StatChip label="Info" value={stats.info} />
                <StatChip label="Runs" value={stats.runs} />
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
                        color: severityColor(logSeverity(ev)),
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
                      style={{
                        color: eventLabelColor(ev.type, logSeverity(ev)),
                      }}
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
