import {useEffect, useRef, useState} from 'react';
import {useLocation} from 'react-router-dom';
import {APP_LOGS_CHANGED_EVENT, getAppLogs, postAppLogs} from '@/api/logs';
import {DIAGNOSTIC_EVENT} from './dom_events';
import {
  APP_LOGS_POLL_MS,
  buildAppLogEntry,
  detailToClientRecord,
  PANEL_LIMIT,
  type DiagnosticLogEventDetail,
  type PersistedAppLogs,
} from './layout_diagnostics_data';

// Fetches the app-wide persisted log: on mount (so the badge count is
// real), whenever `version` bumps (Clear changed the store), whenever
// the api layer announces a change (a click or error was just
// persisted), and on a steady background poll — popover open or not, so
// the badge never depends on opening the panel. While the popover is
// closed only the badge is needed, so those loads fetch a single record
// (the response still carries `total` and `last_id`); opening re-runs
// the effect with a full-window load. The same fetch runs on every
// route, so navigating never changes what the panel shows.
export function usePersistedAppLogs(
  version: number,
  open: boolean,
): PersistedAppLogs {
  const [logs, setLogs] = useState<PersistedAppLogs>({
    entries: [],
    total: 0,
  });
  // The last applied stream state; `withEntries` records whether display
  // entries were built for it. A load whose payload matches — and whose
  // entries the current open state is not missing — applies nothing, so
  // background polls of an unchanged log never re-render.
  const appliedRef = useRef<{
    lastId: number;
    total: number;
    withEntries: boolean;
  } | null>(null);

  useEffect(() => {
    let disposed = false;
    // Requests can resolve out of order (an announce-triggered load can
    // race the poll); only the most recently issued request may apply.
    let latestRequest = 0;
    const load = () => {
      const request = ++latestRequest;
      getAppLogs(0, open ? PANEL_LIMIT : 1)
        .then(payload => {
          if (disposed || request !== latestRequest) return;
          const applied = appliedRef.current;
          if (
            applied &&
            applied.lastId === payload.last_id &&
            applied.total === payload.total &&
            (applied.withEntries || !open)
          ) {
            return;
          }
          // The open-state request already asks for PANEL_LIMIT records,
          // but the cap is enforced here too: whatever the payload size,
          // the panel shows at most the newest PANEL_LIMIT.
          const shown = open ? payload.logs.slice(-PANEL_LIMIT) : [];
          // Number backwards from the stream total so the newest row is
          // always `total`: a capped window shows 151..250, not 1..100.
          const total = Math.max(payload.total, shown.length);
          const first = total - shown.length + 1;
          appliedRef.current = {
            lastId: payload.last_id,
            total: payload.total,
            withEntries: open,
          };
          setLogs({
            entries: shown.map((record, index) =>
              buildAppLogEntry(record, first + index),
            ),
            total,
          });
        })
        .catch(() => {
          if (disposed || request !== latestRequest) return;
          appliedRef.current = null;
          setLogs({entries: [], total: 0});
        });
    };
    load();
    // A hidden tab loads nothing; returning to it runs one immediate
    // load to catch up rather than waiting out the poll interval.
    const loadIfVisible = () => {
      if (!document.hidden) load();
    };
    const timer = window.setInterval(loadIfVisible, APP_LOGS_POLL_MS);
    document.addEventListener('visibilitychange', loadIfVisible);
    window.addEventListener(APP_LOGS_CHANGED_EVENT, load);
    return () => {
      disposed = true;
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', loadIfVisible);
      window.removeEventListener(APP_LOGS_CHANGED_EVENT, load);
    };
  }, [version, open]);

  return logs;
}

// Ships `cosci-diagnostic-event` CustomEvents dispatched anywhere in the
// app to the persisted log, then notifies the caller so the list can
// refresh. Subscribed for the component's whole lifetime (not only while
// the popover is open) so no event is lost.
export function useDiagnosticIngest(onIngested: () => void) {
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
        // Offline or API down: navigation logging is best-effort.
      });
  }, [pathname]);
}
