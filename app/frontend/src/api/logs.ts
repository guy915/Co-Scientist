// Identity headers are required: unidentified deployed callers see no owned
// logs, and their submitted records become ownerless.
import {clientHeaders, fetchJson, jsonRequest} from './runs';

export interface AppLogRecord {
  id: number;
  // Timestamps are Unix seconds, unlike browser millisecond clocks.
  created_at: number;
  level: string;
  levelno: number;
  logger: string;
  message: string;
  run_id: string | null;
  exc_text: string | null;
}

export interface AppLogsPayload {
  // The window contains the newest matches in oldest-first order.
  logs: AppLogRecord[];
  // Poll from the table high-water mark, including hidden records.
  last_id: number;
  total: number;
  // Use the server cursor-window count; subtracting whole-table totals breaks
  // when retention or scoped clears remove earlier rows.
  session_total: number;
}

export function getAppLogs(afterId = 0, limit = 1000): Promise<AppLogsPayload> {
  return fetchJson(`/api/logs?after_id=${afterId}&limit=${limit}`, {
    headers: clientHeaders(),
  });
}

// Notify open panels and badges immediately after writes rather than waiting
// for their next poll.
export const APP_LOGS_CHANGED_EVENT = 'cosci-app-logs-changed';

function announceAppLogsChanged(): void {
  window.dispatchEvent(new Event(APP_LOGS_CHANGED_EVENT));
}

export interface ClientLogRecord {
  message: string;
  level?: string;
  logger?: string;
  run_id?: string;
}

export async function postAppLogs(
  records: ClientLogRecord[],
): Promise<{added: number; last_id: number}> {
  const result = await fetchJson<{added: number; last_id: number}>(
    '/api/logs',
    jsonRequest({records}, /*includeClientId=*/ true),
  );
  announceAppLogsChanged();
  return result;
}

// Send the whole session-anchored diagnostic view: a link cannot reproduce the
// window the scientist chose to report.
export function reportAppLogs(
  report: string,
): Promise<{status: string; chars: number}> {
  return fetchJson(
    '/api/logs/report',
    jsonRequest({report}, /*includeClientId=*/ true),
  );
}

// Operators clear globally; other callers clear only owned records.
export async function deleteAppLogs(): Promise<{deleted: number}> {
  const result = await fetchJson<{deleted: number}>('/api/logs', {
    method: 'DELETE',
    headers: clientHeaders(),
  });
  announceAppLogsChanged();
  return result;
}
