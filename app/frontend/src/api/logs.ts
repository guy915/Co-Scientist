// Persisted application-logs API client. Mirrors GET /api/logs in
// app/logs_api.py: backend log records captured from the Python root
// logger into the app_logs table (run_id is null for records emitted
// outside any run context).
//
// Every request carries the caller's identity headers. The endpoint
// scopes a non-loopback caller to records it submitted plus records for
// runs it owns, so an unidentified request matches nothing: without these
// headers the panel reads as empty in any deployment the browser does not
// reach over loopback, and submitted records are stored ownerless and can
// never be read back.
import {clientHeaders, fetchJson} from './runs';

/** One persisted backend log record. */
export interface AppLogRecord {
  id: number;
  /** Unix seconds. */
  created_at: number;
  /** Level name: DEBUG | INFO | WARNING | ERROR | CRITICAL. */
  level: string;
  levelno: number;
  /** Dotted name of the emitting Python logger. */
  logger: string;
  message: string;
  run_id: string | null;
  /** Formatted traceback text, when an exception was attached. */
  exc_text: string | null;
}

/** The `/api/logs` response envelope. */
export interface AppLogsPayload {
  /** Matching records, oldest-first (the newest `limit` matches). */
  logs: AppLogRecord[];
  /** Table high-water mark; poll again with `after_id` set to this. */
  last_id: number;
  /** Size of the whole matching set, ignoring `after_id` and `limit`. */
  total: number;
  /**
   * Size of the matching set *after* `after_id`, ignoring `limit`: the
   * count of what this request's cursor covers. `total` cannot stand in
   * for it — subtracting a start-of-session snapshot of `total` goes
   * negative the moment retention pruning or a clear drops rows below the
   * cursor, which pins a badge at zero while records keep arriving.
   */
  session_total: number;
}

/**
 * Fetches persisted backend log records, oldest-first.
 *
 * @param afterId Only records with an id greater than this.
 * @param limit Maximum records returned (the newest matches). Defaults to
 *   the server-side maximum so the popover window covers as much of the
 *   log as one request allows.
 */
export function getAppLogs(afterId = 0, limit = 1000): Promise<AppLogsPayload> {
  return fetchJson(`/api/logs?after_id=${afterId}&limit=${limit}`, {
    headers: clientHeaders(),
  });
}

/**
 * Window event fired after this module successfully changes the
 * persisted log (a POST or a clear), so any open Logs panel or badge can
 * refetch immediately instead of waiting for its next poll.
 */
export const APP_LOGS_CHANGED_EVENT = 'cosci-app-logs-changed';

function announceAppLogsChanged(): void {
  window.dispatchEvent(new Event(APP_LOGS_CHANGED_EVENT));
}

/** One frontend record for the ingestion endpoint (POST /api/logs). */
export interface ClientLogRecord {
  message: string;
  /** Level name; unknown values fall back to INFO server-side. */
  level?: string;
  /** Logger suffix; persisted under the `ui.` namespace. */
  logger?: string;
  run_id?: string;
}

/** Persists frontend log records into the app-wide log. */
export async function postAppLogs(
  records: ClientLogRecord[],
): Promise<{added: number; last_id: number}> {
  const result = await fetchJson<{added: number; last_id: number}>(
    '/api/logs',
    {
      method: 'POST',
      headers: {'Content-Type': 'application/json', ...clientHeaders()},
      body: JSON.stringify({records}),
    },
  );
  announceAppLogsChanged();
  return result;
}

/**
 * Deletes persisted log records and returns the deleted count. Operators
 * (loopback callers) clear the whole log; every other caller clears only
 * its own records.
 */
export async function deleteAppLogs(): Promise<{deleted: number}> {
  const result = await fetchJson<{deleted: number}>('/api/logs', {
    method: 'DELETE',
    headers: clientHeaders(),
  });
  announceAppLogsChanged();
  return result;
}
