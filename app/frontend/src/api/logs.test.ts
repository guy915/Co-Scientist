import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {
  APP_LOGS_CHANGED_EVENT,
  deleteAppLogs,
  getAppLogs,
  postAppLogs,
} from './logs';

const runsApiMock = vi.hoisted(() => ({
  fetchJson: vi.fn(),
  clientHeaders: vi.fn(() => ({'X-Client-ID': 'client-7'})),
}));

vi.mock('./runs', () => runsApiMock);

describe('app logs api announcements', () => {
  const listener = vi.fn();

  beforeEach(() => {
    runsApiMock.fetchJson.mockReset();
    listener.mockReset();
    window.addEventListener(APP_LOGS_CHANGED_EVENT, listener);
  });

  afterEach(() => {
    window.removeEventListener(APP_LOGS_CHANGED_EVENT, listener);
  });

  it('announces a successful post so open panels refresh immediately', async () => {
    runsApiMock.fetchJson.mockResolvedValue({added: 1, last_id: 5});

    await postAppLogs([{message: 'clicked something'}]);

    expect(listener).toHaveBeenCalledTimes(1);
  });

  it('announces a successful clear', async () => {
    runsApiMock.fetchJson.mockResolvedValue({deleted: 3});

    await deleteAppLogs();

    expect(listener).toHaveBeenCalledTimes(1);
  });

  // Every read and write must identify the caller. The endpoint scopes a
  // non-loopback caller to its own records, so an unidentified request
  // matches nothing: without these headers the panel is permanently empty
  // in any real deployment, and records the UI submits are stored
  // ownerless and can never be read back.
  it('identifies the caller when reading', async () => {
    runsApiMock.fetchJson.mockResolvedValue({logs: [], last_id: 0, total: 0});

    await getAppLogs();

    const [, init] = runsApiMock.fetchJson.mock.calls[0];
    expect(init.headers).toMatchObject({'X-Client-ID': 'client-7'});
  });

  it('identifies the caller when posting and clearing', async () => {
    runsApiMock.fetchJson.mockResolvedValue({added: 1, last_id: 5});
    await postAppLogs([{message: 'clicked something'}]);
    runsApiMock.fetchJson.mockResolvedValue({deleted: 1});
    await deleteAppLogs();

    for (const [, init] of runsApiMock.fetchJson.mock.calls) {
      expect(init.headers).toMatchObject({'X-Client-ID': 'client-7'});
    }
  });

  it('does not announce failed requests', async () => {
    runsApiMock.fetchJson.mockRejectedValue(new Error('offline'));

    await expect(postAppLogs([{message: 'x'}])).rejects.toThrow('offline');

    expect(listener).not.toHaveBeenCalled();
  });
});
