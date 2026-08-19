import {render, screen} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {describe, expect, it} from 'vitest';
import type {Run} from '@/api/runs';
import {HomeRecentsPanel} from './home_recents';

function discoveryRun(overrides: Partial<Run> = {}): Run {
  return {
    id: 'r1',
    research_goal: 'Find a faster sieve',
    status: 'completed',
    provider: 'engine',
    created_at: Date.now() / 1000 - 600,
    updated_at: Date.now() / 1000,
    completed_at: Date.now() / 1000,
    error: null,
    config: {
      discovery: {objective: {metric: 'score', direction: 'maximize'}},
    },
    top_hypotheses: [],
    variant_count: 12,
    best_fitness: 8.25,
    ...overrides,
  } as Run;
}

function show(run: Run) {
  return render(
    <MemoryRouter>
      <HomeRecentsPanel
        runs={[run]}
        scoresByRunId={{}}
        showAll
        onToggleShowAll={() => {}}
      />
    </MemoryRouter>,
  );
}

describe('a finished discovery run on the home recents', () => {
  it('reports attempts and best score, not winning ideas', () => {
    // It has no ideas and no Elo, so the ideas block rendered empty --
    // indistinguishable from a run that produced nothing.
    show(discoveryRun());
    expect(screen.getByText('12 attempts')).toBeInTheDocument();
    expect(screen.getByText('Best: 8.25')).toBeInTheDocument();
    expect(screen.queryByText('Winning ideas')).toBeNull();
  });

  it('reads a minimized metric in its own units', () => {
    show(
      discoveryRun({
        config: {
          discovery: {objective: {metric: 'seconds', direction: 'minimize'}},
        },
        best_fitness: -1.9,
      } as Partial<Run>),
    );
    expect(screen.getByText('Best: 1.9')).toBeInTheDocument();
  });

  it('omits the score when nothing scored rather than showing zero', () => {
    show(discoveryRun({best_fitness: null, variant_count: 1}));
    expect(screen.getByText('1 attempt')).toBeInTheDocument();
    expect(screen.queryByText(/^Best:/)).toBeNull();
  });

  it('leaves a hypothesis run showing its winning ideas', () => {
    show(
      discoveryRun({
        config: {},
        top_hypotheses: ['A promising mechanism'],
      } as Partial<Run>),
    );
    expect(screen.getByText('Winning ideas')).toBeInTheDocument();
  });
});
