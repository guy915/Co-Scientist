import {resetRunDetailMocks} from './run_detail_api_test_support';
import * as runsApi from '@/api/runs';
import {makeHypothesis, makeMatch} from '@/test_fixtures';
import {screen} from '@testing-library/react';
import {beforeEach, expect, it, vi} from 'vitest';
import {makeRun, renderAt} from './run_detail_test_support';

it('shows the run goal as the report heading', async () => {
  vi.mocked(runsApi.getRun).mockResolvedValue(
    makeRun('Reversing MASLD liver fibrosis'),
  );
  renderAt('/runs/run-1');
  expect(
    await screen.findByRole('heading', {
      level: 1,
      name: /Reversing MASLD liver fibrosis/i,
    }),
  ).toBeInTheDocument();
});

it('leads the overview with a stat sentence and winning ideas', async () => {
  const created = 1_700_000_000;
  vi.mocked(runsApi.getRun).mockResolvedValue(
    makeRun('Study pathway X', {
      created_at: created,
      completed_at: created + 3 * 3600,
    }),
  );
  vi.mocked(runsApi.getHypotheses).mockResolvedValue([
    makeHypothesis({id: 'h1', title: 'Top idea alpha', elo_rating: 1735}),
    makeHypothesis({id: 'h2', title: 'Runner-up beta', elo_rating: 1707}),
  ]);
  vi.mocked(runsApi.getMatches).mockResolvedValue([
    makeMatch(1),
    makeMatch(2),
    makeMatch(3),
  ]);

  renderAt('/runs/run-1/overview');
  await screen.findByText('Summary');

  expect(
    await screen.findByText(
      new RegExp(
        'A total of 2 ideas were explored over 3 hours with the highest ' +
          'Elo rating of 1735 points and a total of 3 matches were ' +
          'played\\.',
      ),
    ),
  ).toBeInTheDocument();
  expect(
    screen.getByRole('heading', {name: /Winning ideas/}),
  ).toBeInTheDocument();
  expect(screen.getByText('Top idea alpha')).toBeInTheDocument();
});

it('shows an error alert when loading fails', async () => {
  vi.mocked(runsApi.getRun).mockRejectedValue(new Error('boom'));
  renderAt('/runs/run-1');
  const alert = await screen.findByRole('alert');
  expect(alert).toHaveTextContent('boom');
});

beforeEach(() => {
  resetRunDetailMocks();
});
