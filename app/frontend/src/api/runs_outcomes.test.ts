import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {addHypothesisOutcome, getHypothesisOutcomes} from './runs';

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

const fetchMock = () => globalThis.fetch as unknown as ReturnType<typeof vi.fn>;

beforeEach(() => vi.stubGlobal('fetch', vi.fn()));
afterEach(() => vi.unstubAllGlobals());

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
});
