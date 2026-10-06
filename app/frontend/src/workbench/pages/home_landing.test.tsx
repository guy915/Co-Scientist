import {fireEvent, render, within} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import HomeLanding from './home_landing';

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

it('shows each tier with the pool sizes the backend runs', () => {
  renderLanding();
  const tiers = document.getElementById('landing-tiers')!;
  const stats = () =>
    within(tiers)
      .getAllByText(/^\d+$/)
      .map(el => el.textContent);
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
