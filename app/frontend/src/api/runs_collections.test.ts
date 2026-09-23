import {describe, it, expect, vi, beforeEach, afterEach} from 'vitest';
import {fetchReportMarkdown, getSupervisorPlan} from './runs';
import {setAccessToken, clearAccessToken} from '@/lib/client_id';

// Tests for the runs_collections.ts clients that outgrew runs.test.ts's
// line budget. The api client reads VITE_API_BASE_URL at module load; in
// the test env it is unset, so all request URLs are relative (no host).

/** Builds a Response-like object carrying a text body. */
function textResponse(status: number, body: string): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: 'Error',
    text: async () => body,
    json: async () => ({}),
  } as unknown as Response;
}

/** The mocked global fetch, narrowed to its mock surface. */
function fetchMock() {
  return globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
}

/** Returns the [url, options] pair fetch was invoked with on the first call. */
function firstCall(): [string, RequestInit | undefined] {
  return fetchMock().mock.calls[0] as [string, RequestInit | undefined];
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('fetchReportMarkdown', () => {
  it('GETs report.md with the auth headers, never query-string auth', async () => {
    // The download must not carry its credential in the URL: query strings
    // leak into history, screenshots, and proxy logs.
    fetchMock().mockResolvedValue(textResponse(200, '# Report'));

    const result = await fetchReportMarkdown('r1');

    const [url, opts] = firstCall();
    expect(url).toBe('/api/runs/r1/report.md');
    expect(url).not.toContain('access_token=');
    expect(url).not.toContain('client_id=');
    expect(
      (opts?.headers as Record<string, string>)['X-Client-ID'],
    ).toBeTruthy();
    expect(result).toBe('# Report');
  });

  it('sends the Bearer token as a header when a researcher session exists', async () => {
    setAccessToken('session-token');
    try {
      fetchMock().mockResolvedValue(textResponse(200, '# Report'));

      await fetchReportMarkdown('r1');

      const [, opts] = firstCall();
      const headers = opts?.headers as Record<string, string>;
      expect(headers['Authorization']).toBe('Bearer session-token');
      expect(headers['X-Client-ID']).toBeUndefined();
      expect(firstCall()[0]).not.toContain('access_token=');
    } finally {
      clearAccessToken();
    }
  });

  it('returns null when the report does not exist yet (404)', async () => {
    fetchMock().mockResolvedValue(textResponse(404, 'not found'));
    expect(await fetchReportMarkdown('r1')).toBeNull();
  });

  it('throws on a non-404 error response', async () => {
    fetchMock().mockResolvedValue(textResponse(500, 'boom'));
    await expect(fetchReportMarkdown('r1')).rejects.toThrow('500 boom');
  });
});

describe('getSupervisorPlan', () => {
  it('fetches the owned allocation ledger using the standard client header', async () => {
    const response = {plan: null, allocations: []};
    fetchMock().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => response,
    } as Response);

    expect(await getSupervisorPlan('r1')).toEqual(response);
    const [url, opts] = firstCall();
    expect(url).toBe('/api/runs/r1/supervisor-plan');
    expect(opts?.method).toBeUndefined();
    expect((opts?.headers as Record<string, string>)['X-Client-ID']).toBeTruthy();
  });
});
