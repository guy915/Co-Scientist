import {render, screen} from '@testing-library/react';
import {MemoryRouter, Route, Routes, useLocation} from 'react-router-dom';
import {makeRunWithSummary, makeSpec} from '@/test_fixtures';
import {ChatHistoryProvider} from '@/shared/hooks/history_context';
import {RunHistoryProvider} from '@/shared/hooks/history_context';
import {RunDetail} from './run_detail';

export const makeRun = (
  goal: string,
  timing?: {created_at: number; completed_at: number},
) =>
  makeRunWithSummary({
    id: 'run-1',
    research_goal: goal,
    config: {
      setup: makeSpec({
        goal,
        requirements: ['Testable'],
        attributes: ['Novel'],
        criteria: ['Feasible'],
      }),
    },
    ...timing,
  });

export function LocationDisplay() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

// Shared history prevents running pages flashing report chrome; match the app's
// provider stack.
export function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <RunHistoryProvider>
        <ChatHistoryProvider>
          <Routes>
            <Route path="/runs/:id" element={<RunDetail />} />
            <Route path="/runs/:id/:tab" element={<RunDetail />} />
          </Routes>
          <LocationDisplay />
        </ChatHistoryProvider>
      </RunHistoryProvider>
    </MemoryRouter>,
  );
}

export const tab = (name: RegExp) => screen.getByRole('link', {name});
