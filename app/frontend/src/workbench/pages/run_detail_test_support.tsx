import {render, screen} from '@testing-library/react';
import {MemoryRouter, Route, Routes, useLocation} from 'react-router-dom';
import type {RunWithSummary} from '@/api/runs';
import {ChatHistoryProvider} from '@/workbench/hooks/history_context';
import {RunHistoryProvider} from '@/workbench/hooks/history_context';
import {RunDetail} from './run_detail';

export const makeRun = (
  goal: string,
  timing?: {created_at: number; completed_at: number},
): RunWithSummary =>
  ({
    id: 'run-1',
    research_goal: goal,
    status: 'completed',
    summary: {events: 0, hypotheses: 0, evidence: 0, matches: 0, reviews: 0},
    config: {
      setup: {
        goal,
        requirements: ['Testable'],
        attributes: ['Novel'],
        criteria: ['Feasible'],
      },
    },
    ...timing,
  }) as unknown as RunWithSummary;

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
