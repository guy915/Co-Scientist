import {describe, it, expect, vi, beforeEach, afterEach} from 'vitest';
import {
  createRun,
  listRuns,
  getRun,
  startRun,
  cancelRun,
  getHypotheses,
  getReport,
  sendMessage,
  getSystemStatus,
  reportMarkdownUrl,
  eventsStreamUrl,
  askQuestionUrl,
} from './runs';

// The api client reads VITE_API_BASE_URL at module load; in the test env it is
// unset, so all request URLs are relative (no host prefix).

/** Builds a minimal Response-like object that resolves the given JSON body. */
function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

/** Builds a Response-like object representing a non-OK HTTP error. */
function errorResponse(status: number, text = 'boom'): Response {
  return {
    ok: false,
    status,
    statusText: 'Error',
    json: async () => ({}),
    text: async () => text,
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

describe('createRun', () => {
  it('POSTs to /api/runs with a JSON body and the client-id header', async () => {
    const run = {id: 'r1', research_goal: 'g'};
    fetchMock().mockResolvedValue(jsonResponse(run));

    const result = await createRun({research_goal: 'g'});

    const [url, opts] = firstCall();
    expect(url).toBe('/api/runs');
    expect(opts?.method).toBe('POST');
    const headers = opts?.headers as Record<string, string>;
    expect(headers['Content-Type']).toBe('application/json');
    expect(headers['X-Client-ID']).toBeTruthy();
    expect(JSON.parse(opts?.body as string)).toEqual({
      research_goal: 'g',
    });
    expect(result).toEqual(run);
  });

  it('throws "<status> <text>" on a non-OK response', async () => {
    fetchMock().mockResolvedValue(errorResponse(500, 'kaboom'));
    await expect(createRun({research_goal: 'g'})).rejects.toThrow('500 kaboom');
  });
});

describe('listRuns', () => {
  it('GETs /api/runs with the client-id header and unwraps .runs', async () => {
    const runs = [{id: 'a'}, {id: 'b'}];
    fetchMock().mockResolvedValue(jsonResponse({runs}));

    const result = await listRuns();

    const [url, opts] = firstCall();
    expect(url).toBe('/api/runs');
    // No explicit method is set on this GET.
    expect(opts?.method).toBeUndefined();
    const headers = opts?.headers as Record<string, string>;
    expect(headers['X-Client-ID']).toBeTruthy();
    expect(result).toEqual(runs);
  });

  it('throws on a non-OK response', async () => {
    fetchMock().mockResolvedValue(errorResponse(403, 'denied'));
    await expect(listRuns()).rejects.toThrow('403 denied');
  });

  it('includes a limit query parameter when requested', async () => {
    fetchMock().mockResolvedValue(jsonResponse({runs: []}));

    await listRuns(1000);

    const [url] = firstCall();
    expect(url).toBe('/api/runs?limit=1000');
  });
});

describe('getRun', () => {
  it('GETs /api/runs/:id without a client-id header and returns the run', async () => {
    const run = {id: 'r7', summary: {events: 1}};
    fetchMock().mockResolvedValue(jsonResponse(run));

    const result = await getRun('r7');

    const [url, opts] = firstCall();
    expect(url).toBe('/api/runs/r7');
    // Bare fetch(url) -- no options object at all.
    expect(opts).toBeUndefined();
    expect(result).toEqual(run);
  });

  it('throws on a non-OK response', async () => {
    fetchMock().mockResolvedValue(errorResponse(404, 'nope'));
    await expect(getRun('missing')).rejects.toThrow('404 nope');
  });
});

describe('startRun', () => {
  it('POSTs to /api/runs/:id/start with the provider body and no client header', async () => {
    fetchMock().mockResolvedValue(jsonResponse({id: 'r1', status: 'queued'}));

    const result = await startRun('r1', {force_provider: 'engine'});

    const [url, opts] = firstCall();
    expect(url).toBe('/api/runs/r1/start');
    expect(opts?.method).toBe('POST');
    const headers = opts?.headers as Record<string, string>;
    expect(headers['Content-Type']).toBe('application/json');
    expect(headers['X-Client-ID']).toBeUndefined();
    expect(JSON.parse(opts?.body as string)).toEqual({
      force_provider: 'engine',
    });
    expect(result).toEqual({id: 'r1', status: 'queued'});
  });

  it('defaults the body to an empty object when no override is given', async () => {
    fetchMock().mockResolvedValue(jsonResponse({id: 'r1', status: 'queued'}));

    await startRun('r1');

    const [, opts] = firstCall();
    expect(JSON.parse(opts?.body as string)).toEqual({});
  });
});

describe('cancelRun', () => {
  it('POSTs to /api/runs/:id/cancel with no headers or body', async () => {
    fetchMock().mockResolvedValue(
      jsonResponse({id: 'r1', status: 'cancelled'}),
    );

    const result = await cancelRun('r1');

    const [url, opts] = firstCall();
    expect(url).toBe('/api/runs/r1/cancel');
    expect(opts?.method).toBe('POST');
    expect(opts?.headers).toBeUndefined();
    expect(opts?.body).toBeUndefined();
    expect(result).toEqual({id: 'r1', status: 'cancelled'});
  });
});

describe('getHypotheses', () => {
  it('GETs /api/runs/:id/hypotheses and unwraps .hypotheses', async () => {
    const hypotheses = [{id: 'h1'}, {id: 'h2'}];
    fetchMock().mockResolvedValue(jsonResponse({hypotheses}));

    const result = await getHypotheses('r1');

    const [url] = firstCall();
    expect(url).toBe('/api/runs/r1/hypotheses');
    expect(result).toEqual(hypotheses);
  });

  it('throws on a non-OK response', async () => {
    fetchMock().mockResolvedValue(errorResponse(500, 'fail'));
    await expect(getHypotheses('r1')).rejects.toThrow('500 fail');
  });
});

describe('getReport', () => {
  it('GETs /api/runs/:id/report and returns the parsed report', async () => {
    const report = {id: 'rep1', run_id: 'r1'};
    fetchMock().mockResolvedValue(jsonResponse(report));

    const result = await getReport('r1');

    const [url] = firstCall();
    expect(url).toBe('/api/runs/r1/report');
    expect(result).toEqual(report);
  });

  it('returns null when the report is not found (404)', async () => {
    fetchMock().mockResolvedValue(errorResponse(404, 'not found'));
    const result = await getReport('r1');
    expect(result).toBeNull();
  });

  it('throws on a non-404 error response', async () => {
    fetchMock().mockResolvedValue(errorResponse(500, 'boom'));
    await expect(getReport('r1')).rejects.toThrow('500 boom');
  });
});

describe('sendMessage', () => {
  it('POSTs the content with the client header and omits kind when absent', async () => {
    const message = {id: 1, content: 'hi'};
    fetchMock().mockResolvedValue(jsonResponse(message));

    const result = await sendMessage('r1', 'hi');

    const [url, opts] = firstCall();
    expect(url).toBe('/api/runs/r1/messages');
    expect(opts?.method).toBe('POST');
    const headers = opts?.headers as Record<string, string>;
    expect(headers['Content-Type']).toBe('application/json');
    expect(headers['X-Client-ID']).toBeTruthy();
    expect(JSON.parse(opts?.body as string)).toEqual({content: 'hi'});
    expect(result).toEqual(message);
  });

  it('includes the kind in the body when provided', async () => {
    fetchMock().mockResolvedValue(jsonResponse({id: 2}));

    await sendMessage('r1', 'steer me', 'steering');

    const [, opts] = firstCall();
    expect(JSON.parse(opts?.body as string)).toEqual({
      content: 'steer me',
      kind: 'steering',
    });
  });

  it('throws "sendMessage <status>" on a non-OK response', async () => {
    fetchMock().mockResolvedValue(errorResponse(400));
    await expect(sendMessage('r1', 'hi')).rejects.toThrow('sendMessage 400');
  });
});

describe('getSystemStatus', () => {
  it('GETs /status and returns the parsed status', async () => {
    const status = {mcp_available: true, model_name: 'deepseek/deepseek-chat'};
    fetchMock().mockResolvedValue(jsonResponse(status));

    const result = await getSystemStatus();

    const [url, opts] = firstCall();
    expect(url).toBe('/status');
    expect(opts).toBeUndefined();
    expect(result).toEqual(status);
  });

  it('throws on a non-OK response', async () => {
    fetchMock().mockResolvedValue(errorResponse(503, 'down'));
    await expect(getSystemStatus()).rejects.toThrow('503 down');
  });
});

describe('url builders', () => {
  it('reportMarkdownUrl points at the run report.md endpoint', () => {
    const url = reportMarkdownUrl('run-42');
    expect(url).toContain('run-42');
    expect(url).toBe('/api/runs/run-42/report.md');
  });

  it('eventsStreamUrl defaults the after cursor to 0', () => {
    const url = eventsStreamUrl('run-42');
    expect(url).toContain('run-42');
    expect(url).toBe('/api/runs/run-42/events?after=0');
  });

  it('eventsStreamUrl includes the provided after cursor', () => {
    expect(eventsStreamUrl('run-42', 17)).toBe(
      '/api/runs/run-42/events?after=17',
    );
  });

  it('askQuestionUrl points at the run ask endpoint', () => {
    const url = askQuestionUrl('run-42');
    expect(url).toContain('run-42');
    expect(url).toBe('/api/runs/run-42/messages/ask');
  });
});
