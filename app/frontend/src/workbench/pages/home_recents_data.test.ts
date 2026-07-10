import {describe, expect, it} from 'vitest';
import type {Run, RunStatus} from '@/api/runs';
import {
  formatHomeRunDate,
  formatHomeRunTimeChip,
  homeRunIdeaTitles,
  homeRunScore,
  homeRunStepIndex,
} from './home_recents_data';

function makeRun(overrides: Partial<Run> = {}): Run {
  return {
    id: 'r1',
    research_goal: 'Investigate glucose homeostasis',
    profile: 'standard',
    status: 'completed',
    provider: 'mock',
    config: {},
    created_at: 1_700_000_000,
    updated_at: 1_700_000_100,
    completed_at: 1_700_000_600,
    error: null,
    ...overrides,
  } as Run;
}

describe('formatHomeRunDate', () => {
  it('formats a unix-seconds timestamp as a long localized date', () => {
    const formatted = formatHomeRunDate(1_700_000_000);
    expect(formatted).toMatch(/\d{4}/);
  });
});

describe('formatHomeRunTimeChip', () => {
  it('shows total time for a completed run with valid timestamps', () => {
    const run = makeRun({
      status: 'completed',
      created_at: 1000,
      completed_at: 1000 + 3600,
    });
    expect(formatHomeRunTimeChip(run)).toBe('Total time: 1 hour');
  });

  it('falls back to a flat 60s phrase for a completed run missing a usable end timestamp', () => {
    const run = makeRun({
      status: 'completed',
      created_at: 1000,
      updated_at: 1000,
      completed_at: null,
    });
    expect(formatHomeRunTimeChip(run)).toBe('Total time: 1 minute');
  });

  it('shows elapsed time under a minute for a freshly started active run', () => {
    const now = Date.now() / 1000;
    const run = makeRun({
      status: 'running',
      created_at: now,
      updated_at: now,
      completed_at: null,
    });
    expect(formatHomeRunTimeChip(run)).toBe('Time elapsed: < 1 minute');
  });

  it('shows a formatted elapsed duration for a longer-running active run', () => {
    const run = makeRun({
      status: 'synthesizing',
      created_at: 1000,
      updated_at: 1000 + 300,
      completed_at: null,
    });
    expect(formatHomeRunTimeChip(run)).toBe('Time elapsed: 5 minutes');
  });

  it('shows the raw capitalized status for a non-active, non-completed run', () => {
    const statuses: RunStatus[] = ['draft', 'failed', 'cancelled', 'blocked'];
    for (const status of statuses) {
      const run = makeRun({status});
      expect(formatHomeRunTimeChip(run)).toBe(
        `Status: ${status.charAt(0).toUpperCase()}${status.slice(1)}`,
      );
    }
  });
});

describe('homeRunScore', () => {
  it('returns null for a run that has not completed', () => {
    expect(homeRunScore(makeRun({status: 'running'}), {r1: 1500})).toBeNull();
  });

  it('returns null when no score entry is recorded yet for the run', () => {
    expect(homeRunScore(makeRun({id: 'unscored'}), {})).toBeNull();
  });

  it('returns the recorded score for a completed run, distinguishing an explicit null', () => {
    expect(homeRunScore(makeRun({id: 'r1'}), {r1: 1620})).toBe(1620);
    expect(homeRunScore(makeRun({id: 'r1'}), {r1: null})).toBeNull();
  });
});

describe('homeRunStepIndex', () => {
  it('maps queued to step 1 and synthesizing to step 4 directly', () => {
    expect(homeRunStepIndex(makeRun({status: 'queued'}))).toBe(1);
    expect(homeRunStepIndex(makeRun({status: 'synthesizing'}))).toBe(4);
  });

  it('advances a running run through steps 2-4 by elapsed minutes', () => {
    const now = Date.now() / 1000;
    expect(
      homeRunStepIndex(
        makeRun({status: 'running', created_at: now, updated_at: now}),
      ),
    ).toBe(2);
    expect(
      homeRunStepIndex(
        makeRun({status: 'running', created_at: now - 90, updated_at: now}),
      ),
    ).toBe(3);
    expect(
      homeRunStepIndex(
        makeRun({status: 'running', created_at: now - 200, updated_at: now}),
      ),
    ).toBe(4);
  });
});

describe('homeRunIdeaTitles', () => {
  it('matches the ferroptosis/pancreatic keyword rule', () => {
    expect(
      homeRunIdeaTitles('Ferroptosis regulators in pancreatic cancer'),
    ).toEqual([
      'Mitochondrial feedback rescue hypothesis',
      'Lipid peroxide buffering threshold hypothesis',
      'Iron-trafficking checkpoint hypothesis',
    ]);
  });

  it('matches the liver-fibrosis keyword rule', () => {
    const titles = homeRunIdeaTitles(
      'Reversing MASLD liver fibrosis via stellate cell reprogramming',
    );
    expect(titles).toContain('Epigenetic stromal reversal hypothesis');
  });

  it('matches the tuberculosis keyword rule', () => {
    expect(
      homeRunIdeaTitles('New therapeutic targets for M.tuberculosis'),
    ).toContain('Metabolic refuge disruption hypothesis');
  });

  it('matches the synaptic pruning keyword rule', () => {
    expect(
      homeRunIdeaTitles('Synaptic pruning and neuroinflammation'),
    ).toContain('Microglial timing-window pruning hypothesis');
  });

  it('falls back to a concise-title-derived set for an unmatched goal', () => {
    const titles = homeRunIdeaTitles('Optimize battery electrolyte chemistry');
    expect(titles).toHaveLength(3);
    expect(titles[1]).toBe('Mechanistic differentiation hypothesis');
    expect(titles[2]).toBe('Evidence-guided intervention hypothesis');
  });
});
