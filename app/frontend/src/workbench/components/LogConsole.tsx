/**
 * Copyright 2026 The Co-Scientist Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import '@material/web/icon/icon.js';
import '@material/web/button/outlined-button.js';
import '@material/web/button/filled-tonal-button.js';
import {useCallback, useEffect, useRef, useState} from 'react';
import {useLocation} from 'react-router-dom';
import {getRunEventsLog, type RunEvent} from '@/api/runs';
import {useIsMobile} from '@/hooks/useMediaQuery';

function extractRunId(pathname: string): string | null {
  const m = pathname.match(/\/runs\/([^/]+)/);
  return m && m[1] !== 'new' ? m[1] : null;
}

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

function logText(events: RunEvent[]): string {
  return events
    .map((ev, i) => {
      const payload = JSON.stringify(ev.payload, null, 2);
      return `#${i + 1} [${fmtTime(ev.created_at)}] ${eventLabel(ev.type)}:\n${payload}`;
    })
    .join('\n\n');
}

export function LogConsole() {
  const [open, setOpen] = useState(false);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLDivElement>(null);
  const location = useLocation();
  const runId = extractRunId(location.pathname);
  const isMobile = useIsMobile();

  const load = useCallback(async () => {
    if (!runId) {
      setEvents([]);
      return;
    }
    setLoading(true);
    try {
      setEvents(await getRunEventsLog(runId));
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, [runId]);

  // Reload whenever the run changes or the panel opens
  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    if (open) void load();
  }, [open, load]);

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

  const handleCopy = async () => {
    await navigator.clipboard.writeText(
      events.length ? logText(events) : '(no events)',
    );
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

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
          {events.length > 0 && (
            <span
              className="inline-flex items-center justify-center rounded-full text-xs font-bold w-5 h-5 ml-1.5"
              style={{backgroundColor: 'rgba(255,255,255,0.25)'}}
            >
              {events.length}
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
                    width: 'min(560px, calc(100vw - 2rem))',
                    maxHeight: '480px',
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
              <span className="font-semibold text-base">Diagnostic Logs</span>
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
                  onclick={(() => void handleCopy()) as EventListener}
                  disabled={!events.length || undefined}
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
              className="flex-1 overflow-y-auto px-4 py-3 space-y-4 text-sm"
              style={{fontFamily: 'ui-monospace, monospace'}}
            >
              {!runId && (
                <p
                  className="text-sm"
                  style={{
                    color: 'var(--md-sys-color-on-surface-variant)',
                    fontFamily: 'sans-serif',
                  }}
                >
                  Open a run to see its diagnostic events.
                </p>
              )}
              {runId && !loading && events.length === 0 && (
                <p
                  className="text-sm"
                  style={{
                    color: 'var(--md-sys-color-on-surface-variant)',
                    fontFamily: 'sans-serif',
                  }}
                >
                  No events recorded for this run yet.
                </p>
              )}
              {events.map((ev, i) => (
                <div key={ev.seq}>
                  <div className="flex items-baseline gap-2 mb-1">
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
