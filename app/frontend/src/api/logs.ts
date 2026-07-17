// Persisted application-logs API client. Mirrors GET /api/logs in
// app/logs_api.py: backend log records captured from the Python root
// logger into the app_logs table, app-wide (run_id is null for records
// emitted outside any run context).
import {fetchJson} from './runs';

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
}

/**
 * Fetches persisted backend log records, oldest-first.
 *
 * @param afterId Only records with an id greater than this.
 * @param limit Maximum records returned (the newest matches).
 */
export function getAppLogs(afterId = 0, limit = 200): Promise<AppLogsPayload> {
  return fetchJson(`/api/logs?after_id=${afterId}&limit=${limit}`);
}
