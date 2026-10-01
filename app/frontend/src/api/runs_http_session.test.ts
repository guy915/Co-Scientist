import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {
  createInterview,
  exchangeAccessCode,
  fetchReportMarkdown,
  getRun,
  listDemoRuns,
} from './runs';
import {
  clearAccessToken,
  getAccessToken,
  setAccessToken,
} from '@/lib/client_id';

const fetchMock = vi.fn<typeof fetch>();

function errorResponse(status: number, message: string): Response {
  return new Response(message, {status});
}

beforeEach(() => {
  clearAccessToken();
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  clearAccessToken();
  vi.unstubAllGlobals();
});

describe('session changes while requests are in flight', () => {
  it('keeps a new session when an anonymous background request returns 401', async () => {
    let respond!: (response: Response) => void;
    fetchMock.mockReturnValue(
      new Promise<Response>(resolve => {
        respond = resolve;
      }),
    );
    const pending = listDemoRuns();
    setAccessToken('new-session');
    respond(errorResponse(401, 'researcher access required'));
    await expect(pending).rejects.toThrow('401');
    expect(getAccessToken()).toBe('new-session');
  });

  it.each([
    ['JSON', () => getRun('r1')],
    ['streaming', () => createInterview('a goal')],
    ['download', () => fetchReportMarkdown('r1')],
  ])(
    'keeps a replacement session when an old %s request returns 401',
    async (_kind, call) => {
      let respond!: (response: Response) => void;
      fetchMock.mockReturnValue(
        new Promise<Response>(resolve => {
          respond = resolve;
        }),
      );
      setAccessToken('old-session');
      const pending = call();
      setAccessToken('replacement-session');
      respond(errorResponse(401, 'token expired'));
      await expect(pending).rejects.toThrow('401');
      expect(getAccessToken()).toBe('replacement-session');
    },
  );

  it('keeps a session when an access-code exchange is refused', async () => {
    setAccessToken('valid-session');
    fetchMock.mockResolvedValue(errorResponse(401, 'invalid access code'));
    await expect(exchangeAccessCode('wrong-invite')).rejects.toThrow('401');
    expect(getAccessToken()).toBe('valid-session');
  });
});
