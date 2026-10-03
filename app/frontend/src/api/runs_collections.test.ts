import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {
  addHypothesisOutcome,
  getHypothesisOutcomeRefinement,
  getHypothesisOutcomes,
  requestHypothesisOutcomeRefinement,
  editInterviewFields,
} from './runs';
import {clearAccessToken, setAccessToken} from '@/lib/client_id';

describe('runs outcomes', () => {
  const row = {
    id: 'out-1',
    run_id: 'run-1',
    hypothesis_id: 'hyp-1',
    author: 'Scientist',
    recorded_at: 1_700_000_000,
    method_protocol: 'Protocol details',
    conditions: 'Cells treated for 24 h',
    measured_observation: 'Signal increased',
    units: 'fold change',
    controls: 'Vehicle control',
    interpretation: 'Consistent with the prediction',
    referenced_evidence_ids: ['ev-1'],
  };

  function response(status: number, body: unknown): Response {
    return {
      ok: status >= 200 && status < 300,
      status,
      statusText: 'Error',
      json: async () => body,
      text: async () => JSON.stringify(body),
    } as Response;
  }

  const fetchMock = () =>
    globalThis.fetch as unknown as ReturnType<typeof vi.fn>;

  beforeEach(() => vi.stubGlobal('fetch', vi.fn()));
  afterEach(() => {
    vi.unstubAllGlobals();
    clearAccessToken();
  });

  describe('hypothesis outcomes API', () => {
    it('loads the owned run outcome collection with the standard client identity', async () => {
      fetchMock().mockResolvedValue(response(200, {outcomes: [row]}));

      await expect(getHypothesisOutcomes('run-1')).resolves.toEqual([row]);
      const [url, options] = fetchMock().mock.calls[0] as [
        string,
        RequestInit | undefined,
      ];
      expect(url).toBe('/api/runs/run-1/outcomes');
      expect(options?.headers).toHaveProperty('X-Client-ID');
    });

    it('submits a scientist-recorded outcome for one hypothesis', async () => {
      fetchMock().mockResolvedValue(response(201, row));
      const input = {
        method_protocol: 'Protocol details',
        conditions: 'Cells treated for 24 h',
        measured_observation: 'Signal increased',
        units: 'fold change',
        controls: 'Vehicle control',
        interpretation: 'Consistent with the prediction',
        referenced_evidence_ids: ['ev-1'],
      };

      await expect(
        addHypothesisOutcome('run-1', 'hyp-1', input),
      ).resolves.toEqual(row);
      const [url, options] = fetchMock().mock.calls[0] as [
        string,
        RequestInit | undefined,
      ];
      expect(url).toBe('/api/runs/run-1/hypotheses/hyp-1/outcomes');
      expect(options?.method).toBe('POST');
      expect(JSON.parse(String(options?.body))).toEqual(input);
      expect(options?.headers).toHaveProperty('X-Client-ID');
    });

    it('replays the same owner-authorized outcome refinement intent', async () => {
      const action = {
        action_id: 'action-1',
        run_id: 'run-1',
        outcome_id: 'out-1',
        hypothesis_id: 'hyp-1',
        task_idempotency_key: 'outcome-refinement:action-1',
        checkpoint_seq: 3,
        context_codepoints: 850,
        status: 'queued',
        child_hypothesis_id: null,
        created_at: 1_700_000_000,
        replayed: true,
      };
      fetchMock().mockResolvedValue(response(202, action));

      await expect(
        requestHypothesisOutcomeRefinement('run-1', 'hyp-1', 'out-1'),
      ).resolves.toEqual(action);
      const [url, options] = fetchMock().mock.calls[0] as [
        string,
        RequestInit | undefined,
      ];
      expect(url).toBe(
        '/api/runs/run-1/hypotheses/hyp-1/outcomes/out-1/refine',
      );
      expect(options?.method).toBe('POST');
      expect(options?.headers).toMatchObject({
        'X-Client-ID': expect.any(String),
        'Idempotency-Key': 'outcome-refinement:run-1:hyp-1:out-1',
      });
      expect(options?.body).toBeUndefined();
    });

    it('loads an existing owner refinement action with the researcher session', async () => {
      const action = {
        action_id: 'action-1',
        run_id: 'run-1',
        outcome_id: 'out-1',
        hypothesis_id: 'hyp-1',
        task_idempotency_key: 'outcome-refinement:action-1',
        checkpoint_seq: 3,
        context_codepoints: 850,
        status: 'queued',
        child_hypothesis_id: null,
        created_at: 1_700_000_000,
        replayed: true,
      };
      setAccessToken('researcher-session');
      fetchMock().mockResolvedValue(response(200, action));

      await expect(
        getHypothesisOutcomeRefinement('run-1', 'hyp-1', 'out-1'),
      ).resolves.toEqual(action);
      const [url, options] = fetchMock().mock.calls[0] as [
        string,
        RequestInit | undefined,
      ];
      expect(url).toBe(
        '/api/runs/run-1/hypotheses/hyp-1/outcomes/out-1/refine',
      );
      expect(options?.method).toBeUndefined();
      expect(options?.headers).toEqual({
        Authorization: 'Bearer researcher-session',
      });
    });

    it('preserves a missing-action 404 for the owner-visible component', async () => {
      fetchMock().mockResolvedValue(
        response(404, {detail: 'run or outcome not found'}),
      );

      await expect(
        getHypothesisOutcomeRefinement('run-1', 'hyp-1', 'out-1'),
      ).rejects.toMatchObject({status: 404});
    });
  });
});

describe('runs interviews', () => {
  function jsonResponse(status: number, body: unknown): Response {
    return {
      ok: status >= 200 && status < 300,
      status,
      statusText: 'OK',
      text: async () => JSON.stringify(body),
      json: async () => body,
    } as unknown as Response;
  }

  function fetchMock() {
    return globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
  }

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
});
