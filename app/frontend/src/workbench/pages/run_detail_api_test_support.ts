import * as runsApi from '@/api/runs';
import type {StreamConnectionState} from '@/hooks/use_run_stream';
import {vi} from 'vitest';
import {makeRun} from './run_detail_test_support';

interface Event {
  seq: number;
  type: string;
  payload: object;
}

const stream = vi.hoisted(() => ({
  events: [] as Event[],
  terminal: false,
  connection: undefined as StreamConnectionState | undefined,
}));

vi.mock('@/hooks/use_run_stream', () => ({useRunStream: () => stream}));

vi.mock('@/workbench/hooks/timers', async importOriginal => {
  const actual =
    await importOriginal<typeof import('@/workbench/hooks/timers')>();
  const timer = {schedule: (run: () => void) => run(), cancel: vi.fn()};
  return {...actual, useResetTimer: () => timer};
});

vi.mock('@/api/runs', async importActual => {
  const actual = await importActual<typeof import('@/api/runs')>();
  return {
    ...actual,
    getRun: vi.fn(),
    getHypotheses: vi.fn(),
    getEvidence: vi.fn(),
    getMatches: vi.fn(),
    getReviews: vi.fn(),
    getClaimEvidence: vi.fn(),
    getSafety: vi.fn(),
    getReport: vi.fn(),
    loadRunHistory: vi.fn(),
    listInterviews: vi.fn(actual.listInterviews),
  };
});

export function setStream(events: Event[]) {
  stream.events = events;
}

export function setTerminal(terminal: boolean) {
  stream.terminal = terminal;
}

export function setConnection(connection: StreamConnectionState) {
  stream.connection = connection;
}

export function resetRunDetailMocks() {
  vi.resetAllMocks();
  stream.events = [];
  stream.terminal = false;
  stream.connection = undefined;
  vi.mocked(runsApi.getRun).mockResolvedValue(makeRun('Study pathway X'));
  for (const fetchRows of [
    runsApi.getHypotheses,
    runsApi.getEvidence,
    runsApi.getMatches,
    runsApi.getReviews,
    runsApi.getClaimEvidence,
    runsApi.getSafety,
    runsApi.loadRunHistory,
  ]) {
    vi.mocked(fetchRows).mockResolvedValue([]);
  }
  vi.mocked(runsApi.getReport).mockResolvedValue(null);
}
