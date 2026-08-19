import {render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';
import type {StreamEvent} from '@/hooks/use_run_stream';
import {ActiveRunView, discoveryProgress} from './run_detail_active';
import type {RunWithStreamState} from './run_detail_data';
import {makeRun} from './run_detail_test_support';

function run(): RunWithStreamState {
  return {
    ...makeRun('Find a faster sieve'),
    status: 'running',
    created_at: Date.now() / 1000 - 5,
    stream_connection: 'open',
  };
}

function variantEvent(
  seq: number,
  fitness: number | null,
  type = 'discovery',
): StreamEvent {
  return {
    seq,
    type,
    payload: {ordinal: seq, fitness, status: 'scored', operator: 'rewrite'},
    created_at: Date.now() / 1000,
  } as StreamEvent;
}

describe('a discovery run in flight', () => {
  it('counts attempts and the best score instead of ideas', () => {
    // Both hypothesis labels sit at 0 for a discovery run's whole
    // duration, so a working search read as a stalled one.
    render(
      <ActiveRunView
        run={run()}
        events={[variantEvent(1, 3), variantEvent(2, 8.25)]}
        evidenceCount={0}
        ideaCount={0}
        isDiscovery
      />,
    );
    expect(screen.getByText('Attempts')).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
    expect(screen.getByText('8.25')).toBeInTheDocument();
    expect(screen.queryByText('Ideas explored')).toBeNull();
  });

  it('reads a minimized objective in its own units', () => {
    render(
      <ActiveRunView
        run={run()}
        events={[variantEvent(1, -1.9)]}
        evidenceCount={0}
        ideaCount={0}
        isDiscovery
        objective={{metric: 'seconds', direction: 'minimize'}}
      />,
    );
    expect(screen.getByText('1.9')).toBeInTheDocument();
  });

  it("leaves a hypothesis run's cards alone", () => {
    render(
      <ActiveRunView run={run()} events={[]} evidenceCount={4} ideaCount={7} />,
    );
    expect(screen.getByText('Sources Analyzed')).toBeInTheDocument();
    expect(screen.getByText('Ideas explored')).toBeInTheDocument();
  });
});

describe('discoveryProgress', () => {
  it('ignores every other kind of event', () => {
    const {attempts} = discoveryProgress([
      variantEvent(1, 3),
      variantEvent(2, 4, 'status'),
      variantEvent(3, 5, 'report'),
    ]);
    expect(attempts).toBe(1);
  });

  it('has no best score until something scores', () => {
    // A crashed attempt is an attempt; it is not a score of zero.
    const progress = discoveryProgress([variantEvent(1, null)]);
    expect(progress.attempts).toBe(1);
    expect(progress.best).toBeNull();
  });
});
