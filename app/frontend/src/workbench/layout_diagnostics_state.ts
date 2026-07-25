import {useEffect, useRef, useState} from 'react';
import {useLocation} from 'react-router-dom';
import {
  APP_LOGS_CHANGED_EVENT,
  getAppLogs,
  postAppLogs,
  type AppLogsPayload,
} from '@/api/logs';
import {DIAGNOSTIC_EVENT} from './dom_events';
import {
  APP_LOGS_POLL_MS,
  buildAppLogEntry,
  detailToClientRecord,
  PANEL_LIMIT,
  type DiagnosticLogEventDetail,
  type PersistedAppLogs,
} from './layout_diagnostics_data';

// The last stream state applied to `logs`: whether display entries were
// built for it (only true while the panel is open, since a closed-state
// poll only needs the badge total). A load whose payload matches — and
// whose entries the current open state is not missing — applies nothing,
// so background polls of an unchanged log never re-render.
interface AppliedLogState {
  lastId: number;
  total: number;
  withEntries: boolean;
}

// Where this browsing session began in the durable, app-wide log. The
// panel shows only records added after this point, so opening the site
// starts on a clean panel instead of the whole retained history.
//
//   - `id`: the log's high-water id at session start; a record is "this
//     session" only when its id is above it.
//   - `total`: the visible-record count at session start.
//     The server's `total` ignores the `after_id` window (it counts the
//     whole visible set), so subtracting this snapshot yields the exact
//     count of records added this session — which drives the badge and
//     the "#N" numbering without a second count query.
//
// The baseline lives in sessionStorage, not in this module's memory,
// because the two events look identical to a module-scoped variable but
// mean opposite things to a reader: closing the tab (or the browser) ends
// the session and should start clean, while reloading the tab is the
// reflex for "did that just get logged?" and must not throw the log away.
// sessionStorage draws exactly that line — it survives a reload of this
// tab and dies with it — and it is per-tab, so two tabs keep their own
// views of the same durable log.
const BASELINE_KEY = 'cosci-logs-session-baseline';

interface SessionBaseline {
  id: number;
  total: number;
}

// Storage can be unavailable or full (private modes, quota); the baseline
// is a convenience, never a reason to break the panel, so every access
// degrades to this process's memory.
let memoryBaseline: SessionBaseline | null = null;

function readBaseline(): SessionBaseline | null {
  try {
    const raw = window.sessionStorage.getItem(BASELINE_KEY);
    if (raw) return JSON.parse(raw) as SessionBaseline;
  } catch {
    // Unreadable storage: fall back to the in-memory copy.
  }
  return memoryBaseline;
}

function writeBaseline(baseline: SessionBaseline): void {
  memoryBaseline = baseline;
  try {
    window.sessionStorage.setItem(BASELINE_KEY, JSON.stringify(baseline));
  } catch {
    // Unwritable storage: the in-memory copy still holds for this load.
  }
}

// Clears the captured session baseline. For tests, which drive many
// independent "page sessions" through one module instance.
export function resetSessionBaselineForTest(): void {
  memoryBaseline = null;
  try {
    window.sessionStorage.removeItem(BASELINE_KEY);
  } catch {
    // Nothing to clear.
  }
}

// The id to page from: everything at or below the session baseline is
// pre-session and never fetched. Zero until the first load of a session
// establishes it.
export function sessionAfterId(): number {
  return readBaseline()?.id ?? 0;
}

// Captures the session baseline from the first payload of a session, and
// re-captures it after a full clear restarts ids below the baseline
// (which would otherwise hide everything forever). Called before the load
// effect's disposed/latest guards on purpose: the baseline is a
// session-global snapshot, and letting a disposed mount load fall through
// without recording it would let a later load capture a baseline that
// already includes this session's own records.
function ensureSessionBaseline(payload: AppLogsPayload): void {
  const baseline = readBaseline();
  if (baseline === null || payload.last_id < baseline.id) {
    writeBaseline({id: payload.last_id, total: payload.total});
  }
}

// Builds the next applied-state marker and displayed logs from a fresh
// payload, scoped to this browsing session.
//
// Only records added after the baseline are shown, so the establishing
// load (whose records all predate the baseline) naturally shows nothing —
// no special case needed. The request already pages from the baseline,
// and the cap is re-enforced here so the panel shows at most the newest
// PANEL_LIMIT. Numbers backwards from the session total so the newest row
// is always `total` (a capped window shows 151..250, not 1..100).
function buildLoadedLogs(
  payload: AppLogsPayload,
  open: boolean,
): {applied: AppliedLogState; logs: PersistedAppLogs} {
  const baseline = readBaseline() ?? {id: payload.last_id, total: 0};
  const session = payload.logs.filter(record => record.id > baseline.id);
  const total = Math.max(0, payload.total - baseline.total);
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

// True when `next` is already reflected in `applied` for the current open
// state, so a background poll of an unchanged session never re-renders.
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

// Fetches this browsing session's slice of the app-wide persisted log: on
// mount (so the badge count is real), whenever `version` bumps (Clear
// changed the store), whenever the api layer announces a change (a click
// or error was just persisted), and on a steady background poll — popover
// open or not, so the badge never depends on opening the panel. Every
// load pages from the session baseline, so pre-session history is never
// fetched however deep the retained log is; the session count stays cheap
// to keep current whether the panel is open or closed. The same fetch
// runs on every route, so navigating never changes what the panel shows.
// Wires `load` to run once immediately, on a steady background poll (a
// hidden tab loads nothing; foregrounding runs one immediate catch-up load
// rather than waiting out the interval), and whenever the api layer
// announces the persisted log changed. Returns the cleanup.
function subscribeToLogPolling(load: () => void): () => void {
  load();
  const loadIfVisible = () => {
    if (!document.hidden) load();
  };
  const timer = window.setInterval(loadIfVisible, APP_LOGS_POLL_MS);
  document.addEventListener('visibilitychange', loadIfVisible);
  window.addEventListener(APP_LOGS_CHANGED_EVENT, load);
  return () => {
    window.clearInterval(timer);
    document.removeEventListener('visibilitychange', loadIfVisible);
    window.removeEventListener(APP_LOGS_CHANGED_EVENT, load);
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
    let disposed = false;
    // Requests can resolve out of order (an announce-triggered load can
    // race the poll); only the most recently issued request may apply.
    let latestRequest = 0;
    const load = () => {
      const request = ++latestRequest;
      // Always page the newest PANEL_LIMIT of the session (from the
      // baseline), so the badge count is right whether the panel is open
      // or closed; only display entries are gated on `open`.
      getAppLogs(sessionAfterId(), PANEL_LIMIT)
        .then(payload => {
          // Record the baseline before the guards: a disposed mount load
          // must still anchor the session, or a later load anchors it to a
          // payload that already contains this session's records.
          ensureSessionBaseline(payload);
          if (disposed || request !== latestRequest) return;
          const {applied, logs: nextLogs} = buildLoadedLogs(payload, open);
          if (isAlreadyApplied(appliedRef.current, applied, open)) return;
          appliedRef.current = applied;
          setLogs(nextLogs);
        })
        .catch(() => {
          if (disposed || request !== latestRequest) return;
          appliedRef.current = null;
          setLogs({entries: [], total: 0});
        });
    };
    const unsubscribe = subscribeToLogPolling(load);
    return () => {
      disposed = true;
      unsubscribe();
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
