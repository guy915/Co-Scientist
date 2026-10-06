import {render} from '@testing-library/react';
import type {ComponentProps} from 'react';
import {makeRunWithSummary} from '@/test_fixtures';
import type {Report, RunWithSummary} from '@/api/runs';
import {ResearchOverviewView} from './run_detail_overview';

export function makeRun(
  overrides: Partial<RunWithSummary> = {},
): RunWithSummary {
  return makeRunWithSummary({
    id: 'run-1',
    research_goal: 'Study pathway X',
    created_at: 1_700_000_000,
    completed_at: 1_700_000_000 + 3 * 3600,
    ...overrides,
  });
}

export function makeReport(overrides: Partial<Report['payload']> = {}): Report {
  return {
    id: 'rep-1',
    run_id: 'run-1',
    markdown_path: '',
    created_at: 1,
    payload: {
      research_goal: 'Study pathway X',
      provider: 'mock',
      leaderboard: [],
      ...overrides,
    },
  };
}

export function renderOverview(
  props: Partial<ComponentProps<typeof ResearchOverviewView>> = {},
) {
  return render(
    <ResearchOverviewView
      run={makeRun()}
      report={null}
      hypotheses={[]}
      matches={[]}
      {...props}
    />,
  );
}
