import {render, screen} from '@testing-library/react';
import {it, expect, vi} from 'vitest';
import {MemoryRouter, Route, Routes} from 'react-router-dom';
import {ReportTabNav} from './run_detail_shell';
import {TABS, type TabName} from '../run_tabs';

// jsdom cannot measure clipping; stub TruncatedLabel to observe the rendering
// boundary.
vi.mock('../components/truncated_label', () => ({
  TruncatedLabel: ({text}: {text: string}) => (
    <span data-testid="truncated-label">{text}</span>
  ),
}));

function renderTabs(
  activeTab: TabName = 'details',
  tabs: readonly TabName[] = TABS,
) {
  return render(
    <MemoryRouter initialEntries={[`/runs/run-1/${activeTab}`]}>
      <Routes>
        <Route
          path="/runs/:id/:tab"
          element={
            <ReportTabNav
              activeTab={activeTab}
              onTabChange={() => {}}
              tabs={tabs}
            />
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

it('renders every tab label through TruncatedLabel rather than a bare span', () => {
  renderTabs();
  expect(screen.getAllByTestId('truncated-label')).toHaveLength(TABS.length);
});

// Imperative truncation shortens content-derived names; explicit aria-label
// retains the full name.
it('gives each tab link an explicit aria-label so its accessible name survives truncation', () => {
  renderTabs();
  expect(screen.getByRole('link', {name: 'Research Overview'})).toHaveAttribute(
    'aria-label',
    'Research Overview',
  );
});
