import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {APP_LOGS_CHANGED_EVENT, deleteAppLogs, postAppLogs} from './logs';

const runsApiMock = vi.hoisted(() => ({fetchJson: vi.fn()}));

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

  it('does not announce failed requests', async () => {
    runsApiMock.fetchJson.mockRejectedValue(new Error('offline'));

    await expect(postAppLogs([{message: 'x'}])).rejects.toThrow('offline');

    expect(listener).not.toHaveBeenCalled();
  });
});
