// Tests for the runs_interviews.ts field-editing client. The api client
// reads VITE_API_BASE_URL at module load; in the test env it is unset, so
// all request URLs are relative (no host).

import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {editInterviewFields} from './runs_interviews';

/** Builds a Response-like object carrying a JSON body. */
function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: 'OK',
    text: async () => JSON.stringify(body),
    json: async () => body,
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

describe('editInterviewFields', () => {
  it('PUTs the four fields to /fields (the endpoint is PUT-only)', async () => {
    const updated = {id: 'interview-1', fields: {}};
    fetchMock().mockResolvedValue(jsonResponse(200, updated));

    const fields = {
      research_challenge: 'Explain treatment resistance.',
      focus_area: ['Tumor metabolism'],
      preferences: ['Prioritize human evidence'],
      title: 'Resistance mechanisms',
    };
    const result = await editInterviewFields('interview-1', fields);

    const [url, opts] = firstCall();
    expect(url).toBe('/api/interviews/interview-1/fields');
    expect(opts?.method).toBe('PUT');
    expect(JSON.parse(opts?.body as string)).toEqual(fields);
    expect(result).toEqual(updated);
  });
});
