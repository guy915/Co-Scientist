import {beforeEach, describe, expect, it} from 'vitest';
import {
  offlineAnswer,
  offlineCreateRun,
  offlineGetRun,
  offlineHypotheses,
  offlineListDemoRuns,
  offlineListMessages,
  offlineListRuns,
  offlineReport,
  offlineStartRun,
} from './offline_runs';

describe('offline_runs', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('lists deterministic demo runs without adding them to stored user runs', () => {
    const demos = offlineListDemoRuns();

    expect(demos.map(run => run.id)).toContain('demo-ferroptosis');
    expect(demos.every(run => run.is_demo)).toBe(true);
    expect(offlineListRuns()).toEqual([]);
  });

  it('creates a draft run and materializes artifacts when started', () => {
    const draft = offlineCreateRun({
      research_goal: 'Investigate glucose homeostasis under cold stress.',
      requirements: ['Use human-relevant assays.'],
      attributes: ['Mechanistically specific'],
      criteria: ['Clear experimental readout'],
      focus: 'prefer_novelty',
      tier: 'extended',
    });

    expect(draft.status).toBe('draft');
    expect(draft.config.setup?.requirements).toEqual([
      'Use human-relevant assays.',
    ]);
    expect(offlineListRuns()).toHaveLength(1);
    expect(offlineHypotheses(draft.id)).toEqual([]);
    expect(offlineReport(draft.id)).toBeNull();

    expect(offlineStartRun(draft.id)).toEqual({
      id: draft.id,
      status: 'completed',
    });

    const completed = offlineGetRun(draft.id);
    expect(completed.status).toBe('completed');
    expect(completed.summary.hypotheses).toBeGreaterThan(0);
    expect(offlineHypotheses(draft.id)[0].title).toMatch(/^H1:/);
    expect(offlineReport(draft.id)?.payload.leaderboard).not.toHaveLength(0);
  });

  it('stores offline Q&A messages with the generated answer', () => {
    const run = offlineCreateRun({
      research_goal: 'Find biofilm resistance mechanisms.',
    });

    const answer = offlineAnswer(run.id, 'What is the leading idea?');
    const messages = offlineListMessages(run.id);

    expect(answer.sender).toBe('system');
    expect(messages).toHaveLength(2);
    expect(messages[0]).toMatchObject({
      sender: 'user',
      content: 'What is the leading idea?',
      kind: 'qa',
    });
    expect(messages[1].content).toContain('highest-Elo hypothesis');
  });
});
