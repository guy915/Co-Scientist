import {fireEvent, render, screen, within} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import HomeLanding from './home_landing';
import {INITIAL_ELO, LANDING_SECTIONS} from './home_landing_content';
import {simulateEloHistory} from './home_landing_elo';

const scrollIntoView = vi.fn();

beforeEach(() => {
  Element.prototype.scrollIntoView = scrollIntoView;
});

afterEach(() => {
  scrollIntoView.mockReset();
});

function renderLanding(path = '/') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <HomeLanding />
    </MemoryRouter>,
  );
}

it('answers what the app is and how to start a run', () => {
  renderLanding();
  const faq = document.getElementById('faq')!;
  expect(within(faq).getByText('What is Co-Scientist?')).toBeInTheDocument();
  expect(within(faq).getByText('How do I start a run?')).toBeInTheDocument();
  expect(
    within(faq).getByText('Where does my API key go?'),
  ).toBeInTheDocument();
});

// The FAQ used to carry a "Are there keyboard shortcuts?" entry, because the
// two shortcuts it described had no other discoverable surface. Both are
// gone, and the FAQ is the one place a reader would look to find out that
// they exist -- documenting a binding the app no longer honors would be
// worse than saying nothing, so the entry has to go with them. See
// layout_no_shortcuts.test.tsx for the check that none came back.
it('promises no keyboard shortcuts', () => {
  renderLanding();
  const faq = document.getElementById('faq')!;
  expect(within(faq).queryByText(/keyboard shortcut/i)).toBeNull();
  expect(within(faq).queryByText(/arrow key/i)).toBeNull();
});

it('gives every rail tab a section to scroll to', () => {
  renderLanding();
  const rail = screen.getByRole('navigation', {name: 'Landing sections'});
  for (const {id, label} of LANDING_SECTIONS) {
    expect(document.getElementById(id)).not.toBeNull();
    fireEvent.click(within(rail).getByRole('link', {name: label}));
  }
  expect(scrollIntoView).toHaveBeenCalledTimes(LANDING_SECTIONS.length);
});

it('shows each tier with the pool sizes the backend runs', () => {
  renderLanding();
  const tiers = document.getElementById('landing-tiers')!;
  const stats = () =>
    within(tiers)
      .getAllByText(/^\d+$/)
      .map(el => el.textContent);
  // Standard is the default tier.
  expect(stats()).toEqual(['32', '8', '2']);
  fireEvent.click(within(tiers).getByRole('button', {name: 'Ultra'}));
  expect(stats()).toEqual(['96', '16', '4']);
  fireEvent.click(within(tiers).getByRole('button', {name: 'Express'}));
  expect(stats()).toEqual(['12', '4', '1']);
  expect(within(tiers).getByText('evolution cycle')).toBeInTheDocument();
});

it('opens on the FAQ when the address asks for it', () => {
  vi.useFakeTimers();
  renderLanding('/#faq');
  vi.advanceTimersByTime(100);
  vi.useRealTimers();
  expect(scrollIntoView).toHaveBeenCalled();
  expect(scrollIntoView.mock.contexts.at(-1)).toBe(
    document.getElementById('faq'),
  );
});

it('plays the chart tournament deterministically and zero-sum', () => {
  const first = simulateEloHistory();
  const second = simulateEloHistory();
  expect(first).toEqual(second);
  expect(first.history).toHaveLength(65);
  for (const snapshot of first.history) {
    const mean = snapshot.reduce((a, b) => a + b, 0) / snapshot.length;
    expect(mean).toBeCloseTo(INITIAL_ELO, 6);
  }
  const final = first.history.at(-1)!;
  expect(final[first.leader]).toBe(Math.max(...final));
  expect(final[first.leader]).toBeGreaterThan(INITIAL_ELO);
});
