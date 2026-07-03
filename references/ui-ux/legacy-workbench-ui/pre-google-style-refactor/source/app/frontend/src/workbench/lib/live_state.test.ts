import {describe, it, expect} from 'vitest';
import {selectLiveLeaderboard} from './live_state';
import type {StreamEvent} from '@/hooks/use_run_stream';

function ev(seq: number, type: string, payload: Record<string, unknown>) {
  return {seq, type, payload} satisfies StreamEvent;
}

const standing = (rank: number, id: string, elo: number) => ({
  rank,
  id,
  title: `Hypothesis ${id}`,
  elo,
  wins: 0,
  losses: 0,
});

describe('selectLiveLeaderboard', () => {
  it('returns the latest non-empty leaderboard snapshot', () => {
    const events: StreamEvent[] = [
      ev(1, 'engine.generate', {leaderboard: [standing(1, 'a', 1200)]}),
      ev(2, 'engine.ranking', {
        leaderboard: [standing(1, 'b', 1240), standing(2, 'a', 1180)],
      }),
    ];
    const lb = selectLiveLeaderboard(events);
    expect(lb.map(s => s.id)).toEqual(['b', 'a']);
    expect(lb[0].elo).toBe(1240);
  });

  it('skips later events that carry no standings', () => {
    const events: StreamEvent[] = [
      ev(1, 'engine.ranking', {leaderboard: [standing(1, 'a', 1300)]}),
      ev(2, 'engine.proximity', {leaderboard: []}),
      ev(3, 'report', {}),
      ev(4, 'status', {status: 'completed'}),
    ];
    expect(selectLiveLeaderboard(events)[0].id).toBe('a');
  });

  it('returns empty when no event has standings', () => {
    const events: StreamEvent[] = [
      ev(1, 'engine.supervisor', {hypothesis_count: 0}),
    ];
    expect(selectLiveLeaderboard(events)).toEqual([]);
  });

  it('ignores malformed leaderboard payloads', () => {
    const events: StreamEvent[] = [
      ev(1, 'engine.ranking', {leaderboard: [{nope: true}]}),
    ];
    expect(selectLiveLeaderboard(events)).toEqual([]);
  });
});
