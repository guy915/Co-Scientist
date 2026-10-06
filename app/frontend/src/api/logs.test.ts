import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {
  APP_LOGS_CHANGED_EVENT,
  deleteAppLogs,
  getAppLogs,
  postAppLogs,
} from './logs';

const httpMock = vi.hoisted(() => {
  const clientHeaders = vi.fn(() => ({'X-Client-ID': 'client-7'}));
  // Build headers through the identity mock so requests retain their owner.
  const jsonRequest = vi.fn(
    (body: unknown, includeClientId = false): RequestInit => ({
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(includeClientId ? clientHeaders() : {}),
      },
      body: JSON.stringify(body),
    }),
  );
  return {fetchJson: vi.fn(), clientHeaders, jsonRequest};
});

vi.mock('./runs', () => httpMock);

const listener = vi.fn();

beforeEach(() => {
  httpMock.fetchJson.mockReset();
  listener.mockReset();
  window.addEventListener(APP_LOGS_CHANGED_EVENT, listener);
});

afterEach(() => {
  window.removeEventListener(APP_LOGS_CHANGED_EVENT, listener);
});

it('announces a successful post so open panels refresh', async () => {
  httpMock.fetchJson.mockResolvedValue({added: 1, last_id: 5});

  await postAppLogs([{message: 'clicked something'}]);

  expect(listener).toHaveBeenCalledTimes(1);
});

// Unidentified remote log requests match nothing and create unreadable
// ownerless records.
it('identifies the caller when reading', async () => {
  httpMock.fetchJson.mockResolvedValue({logs: [], last_id: 0, total: 0});

  await getAppLogs();

  const [, init] = httpMock.fetchJson.mock.calls[0];
  expect(init.headers).toMatchObject({'X-Client-ID': 'client-7'});
});

it('identifies the caller when posting and clearing', async () => {
  httpMock.fetchJson.mockResolvedValue({added: 1, last_id: 5});
  await postAppLogs([{message: 'clicked something'}]);
  httpMock.fetchJson.mockResolvedValue({deleted: 1});
  await deleteAppLogs();

  for (const [, init] of httpMock.fetchJson.mock.calls) {
    expect(init.headers).toMatchObject({'X-Client-ID': 'client-7'});
  }
});

it('does not announce failed requests', async () => {
  httpMock.fetchJson.mockRejectedValue(new Error('offline'));

  await expect(postAppLogs([{message: 'x'}])).rejects.toThrow('offline');

  expect(listener).not.toHaveBeenCalled();
});
