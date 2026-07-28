import {act, render, screen} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {afterEach, expect, it, vi} from 'vitest';
import {makeRun} from '@/test_fixtures';
import {HomeRecentsPanel} from './home_recents';

const START_MS = Date.UTC(2026, 0, 1);

function renderPanel(createdAtSeconds: number) {
  const run = makeRun({
    status: 'running',
    created_at: createdAtSeconds,
    // The last server write, deliberately stale: an executing run's elapsed
    // chip must not be pinned to it.
    updated_at: createdAtSeconds,
    completed_at: null,
  });
  return render(
    <MemoryRouter>
      <HomeRecentsPanel
        runs={[run]}
        scoresByRunId={{}}
        showAll={false}
        onToggleShowAll={() => {}}
      />
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.useRealTimers();
});

it('advances an active run’s elapsed chip as the clock ticks', () => {
  vi.useFakeTimers();
  vi.setSystemTime(START_MS);
  renderPanel(START_MS / 1000 - 30);

  expect(screen.getByText('Time elapsed: < 1 minute')).toBeInTheDocument();

  // 30s + 60s = 90s, which rounds to two minutes. No refetch happens here:
  // the chip has to move on its own clock.
  act(() => {
    vi.advanceTimersByTime(60_000);
  });
  expect(screen.getByText('Time elapsed: 2 minutes')).toBeInTheDocument();
});
