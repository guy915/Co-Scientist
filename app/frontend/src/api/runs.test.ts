import {describe, it, expect, vi, beforeEach, afterEach} from 'vitest';
import {
  createRun,
  listRuns,
  listDemoRuns,
  loadRunHistory,
  getRun,
  startRun,
  getHypotheses,
  getEvidence,
  getMatches,
  getReviews,
  getReport,
  getSupervisorPlan,
  runGoal,
  createInterview,
} from './runs';
import type {Run} from './wire_runs';
import {
  setAccessToken,
  getAccessToken,
  clearAccessToken,
} from '@/lib/client_id';

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
  it('POSTs to /api/runs with a JSON body and client-id header', async () => {
    const run = {id: 'r1', research_goal: 'g'};
    fetchMock().mockResolvedValue(jsonResponse(run));

    const result = await createRun({research_goal: 'g'});

    const [url, opts] = firstCall();
    expect(url).toBe('/api/runs');
    expect(opts?.method).toBe('POST');
    const headers = opts?.headers as Record<string, string>;
    expect(headers['Content-Type']).toBe('application/json');
    expect(headers['X-Client-ID']).toBeTruthy();
    expect(headers['Idempotency-Key']).toBeUndefined();
    expect(JSON.parse(opts?.body as string)).toEqual({
      research_goal: 'g',
    });
    expect(result).toEqual(run);
  });

  it('sends an optional idempotency key with the exact create body', async () => {
    fetchMock().mockResolvedValue(jsonResponse({id: 'r2'}));
    const payload = {
      research_goal: 'g',
      interview_id: 'chat-1',
      document_ids: ['doc-1'],
    };

    await createRun(payload, {idempotencyKey: 'create-key-1'});

    const [, opts] = firstCall();
    const headers = opts?.headers as Record<string, string>;
    expect(headers['Idempotency-Key']).toBe('create-key-1');
    expect(opts?.body).toBe(JSON.stringify(payload));
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

  it('does not replace network failures with offline sample runs', async () => {
    fetchMock().mockRejectedValue(new TypeError('Failed to fetch'));
    await expect(listRuns()).rejects.toThrow('Failed to fetch');
  });

  it('includes a limit query parameter when requested', async () => {
    fetchMock().mockResolvedValue(jsonResponse({runs: []}));

    await listRuns(1000);

    const [url] = firstCall();
    expect(url).toBe('/api/runs?limit=1000');
  });
});

describe('loadRunHistory', () => {
  it('merges demonstration runs when demos are included', async () => {
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse({runs: [{id: 'owned', updated_at: 2}]}),
      )
      .mockResolvedValueOnce(
        jsonResponse({runs: [{id: 'demo', updated_at: 1}]}),
      );

    const result = await loadRunHistory();

    expect(result.map(run => run.id)).toEqual(['owned', 'demo']);
  });
});

describe('getRun', () => {
  it('GETs /api/runs/:id with the ownership header', async () => {
    const run = {id: 'r7', summary: {events: 1}};
    fetchMock().mockResolvedValue(jsonResponse(run));

    const result = await getRun('r7');

    const [url, opts] = firstCall();
    expect(url).toBe('/api/runs/r7');
    expect(
      (opts?.headers as Record<string, string>)['X-Client-ID'],
    ).toBeTruthy();
    expect(result).toEqual(run);
  });

  it('throws on a non-OK response', async () => {
    fetchMock().mockResolvedValue(errorResponse(404, 'nope'));
    await expect(getRun('missing')).rejects.toThrow('404 nope');
  });
});

describe('startRun', () => {
  it('POSTs to /api/runs/:id/start with owner data', async () => {
    fetchMock().mockResolvedValue(jsonResponse({id: 'r1', status: 'queued'}));

    const result = await startRun('r1');

    const [url, opts] = firstCall();
    expect(url).toBe('/api/runs/r1/start');
    expect(opts?.method).toBe('POST');
    const headers = opts?.headers as Record<string, string>;
    expect(headers['Content-Type']).toBe('application/json');
    expect(headers['X-Client-ID']).toBeTruthy();
    expect(JSON.parse(opts?.body as string)).toEqual({});
    expect(result).toEqual({id: 'r1', status: 'queued'});
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

describe('collection fetchers unwrap their keyed payload', () => {
  // getEvidence/getMatches/getReviews share one shape: GET the run-scoped
  // endpoint and unwrap the same-named array from the response body.
  const unwrapCases: [string, (id: string) => Promise<unknown>, unknown[]][] = [
    ['evidence', getEvidence, [{id: 'e1'}]],
    ['matches', getMatches, [{id: 1}]],
    ['reviews', getReviews, [{id: 1}]],
  ];

  it.each(unwrapCases)(
    'GETs /api/runs/:id/%s and unwraps it',
    async (key, fetcher, value) => {
      fetchMock().mockResolvedValue(jsonResponse({[key]: value}));

      const result = await fetcher('r1');

      expect(firstCall()[0]).toBe(`/api/runs/r1/${key}`);
      expect(result).toEqual(value);
    },
  );
});

describe('listDemoRuns', () => {
  it('GETs /api/runs/demo with no client-id and unwraps .runs', async () => {
    const runs = [{id: 'demo-1'}];
    fetchMock().mockResolvedValue(jsonResponse({runs}));

    const result = await listDemoRuns();

    const [url, opts] = firstCall();
    expect(url).toBe('/api/runs/demo');
    expect(opts).toBeUndefined();
    expect(result).toEqual(runs);
  });

  it('throws on a non-OK response', async () => {
    fetchMock().mockResolvedValue(errorResponse(500, 'fail'));
    await expect(listDemoRuns()).rejects.toThrow('500 fail');
  });
});

it('merges owned and demo runs, de-duped and sorted newest first', async () => {
  fetchMock().mockImplementation((url: string) => {
    if (url.includes('/demo')) {
      // Demo runs are appended after owned runs, so a shared id here wins
      // the de-dup (later demo entries replace owned entries).
      return Promise.resolve(
        jsonResponse({
          runs: [
            {id: 'shared', updated_at: 99},
            {id: 'other', updated_at: 50},
          ],
        }),
      );
    }
    return Promise.resolve(
      jsonResponse({runs: [{id: 'shared', updated_at: 1}]}),
    );
  });

  const result = await loadRunHistory();

  expect(result.map(run => run.id)).toEqual(['shared', 'other']);
  expect(result.find(run => run.id === 'shared')?.updated_at).toBe(99);
});

it('degrades a failing demo source without blocking owned runs', async () => {
  fetchMock().mockImplementation((url: string) => {
    if (url.includes('/demo')) {
      return Promise.reject(new TypeError('Failed to fetch'));
    }
    return Promise.resolve(
      jsonResponse({runs: [{id: 'owned', updated_at: 10}]}),
    );
  });

  const result = await loadRunHistory();

  expect(result).toEqual([{id: 'owned', updated_at: 10}]);
});

it('degrades a failing owned source without blocking demo runs', async () => {
  fetchMock().mockImplementation((url: string) => {
    if (url.includes('/demo')) {
      return Promise.resolve(
        jsonResponse({runs: [{id: 'demo-1', updated_at: 10}]}),
      );
    }
    return Promise.reject(new TypeError('Failed to fetch'));
  });

  const result = await loadRunHistory();

  expect(result).toEqual([{id: 'demo-1', updated_at: 10}]);
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

describe('runGoal', () => {
  it('prefers the durable setup goal over the top-level research goal', () => {
    const run = {
      config: {setup: {goal: 'Setup goal'}},
      research_goal: 'Top-level goal',
    } as unknown as Run;
    expect(runGoal(run)).toBe('Setup goal');
  });

  it('falls back to the top-level goal with no setup goal', () => {
    const run = {
      config: {},
      research_goal: 'Top-level goal',
    } as unknown as Run;
    expect(runGoal(run)).toBe('Top-level goal');
  });

  it('returns an empty string when the run is not yet loaded', () => {
    expect(runGoal(null)).toBe('');
    expect(runGoal(undefined)).toBe('');
  });
});

describe('error message formatting', () => {
  it('reports "API unavailable" for an empty-bodied 500 response', async () => {
    fetchMock().mockResolvedValue(errorResponse(500, ''));
    await expect(getRun('r1')).rejects.toThrow('API unavailable');
  });

  it('falls back to statusText when reading the error body fails', async () => {
    const response = {
      ok: false,
      status: 502,
      statusText: 'Bad Gateway',
      json: async () => ({}),
      text: () => Promise.reject(new Error('stream closed')),
    } as unknown as Response;
    fetchMock().mockResolvedValue(response);
    await expect(getRun('r1')).rejects.toThrow('502 Bad Gateway');
  });
});

describe('expired researcher session', () => {
  afterEach(() => clearAccessToken());

  it('clears a stored access token when a request returns 401', async () => {
    // A researcher session token expires server-side after 12h. Without this,
    // clientHeaders keeps sending the dead Bearer token, every request 401s,
    // and the tab is bricked until sessionStorage is cleared by hand.
    setAccessToken('expired-token');
    fetchMock().mockResolvedValue(errorResponse(401, 'token expired'));

    await expect(getRun('r1')).rejects.toThrow('401');

    expect(getAccessToken()).toBeNull();
  });

  it('keeps the access token on a non-401 error', async () => {
    setAccessToken('good-token');
    fetchMock().mockResolvedValue(errorResponse(500, 'server error'));

    await expect(getRun('r1')).rejects.toThrow('500');

    expect(getAccessToken()).toBe('good-token');
  });

  it('clears a stored token when a streaming request returns 401', async () => {
    // createInterview runs on the home page before any run exists, so its
    // streaming path is the one a stale session hits first; a 401 there must
    // clear the token too, not just the plain-JSON calls.
    setAccessToken('expired-token');
    fetchMock().mockResolvedValue(errorResponse(401, 'token expired'));

    await expect(createInterview('a goal')).rejects.toThrow('401');

    expect(getAccessToken()).toBeNull();
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
    expect(
      (opts?.headers as Record<string, string>)['X-Client-ID'],
    ).toBeTruthy();
  });
});
