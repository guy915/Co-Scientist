import {render, screen} from '@testing-library/react';
import {it, expect, vi} from 'vitest';
import {MemoryRouter, Route, Routes} from 'react-router-dom';
import {ReportTabNav} from './run_detail_shell';
import {TABS, type TabName} from '../run_tabs';

// The tab strip is a 4-column grid with min-w-0 cells and no width floor on
// the label span, sitting inside ancestors that clip horizontal overflow
// (see the M2 breakpoint/clipping fix) -- so a label that did not fit its
// column was silently cut off by the ancestor's overflow: hidden rather than
// shrinking on purpose. Stubbing TruncatedLabel lets the test see which
// component actually rendered each label without depending on jsdom's
// (always-zero) layout measurements.
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
  expect(screen.getAllByTestId('truncated-label')).toHaveLength(4);
});

// TruncatedLabel rewrites its span's textContent imperatively (see its own
// docstring), which in a real browser truncates the accessible name derived
// from content along with the visible text. An explicit aria-label keeps the
// link's name whole regardless of what the label ends up fitting.
it('gives each tab link an explicit aria-label so its accessible name survives truncation', () => {
  renderTabs();
  expect(screen.getByRole('link', {name: 'Research Overview'})).toHaveAttribute(
    'aria-label',
    'Research Overview',
  );
});
