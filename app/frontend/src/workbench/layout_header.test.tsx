import {render, screen} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {beforeEach, expect, it} from 'vitest';
import {type Audience, AudienceProvider} from './audience_context';
import {GOOGLE_PROPOSALS} from './audience_content';
import {ShellHeader} from './layout_header';

// The audience is declared to the provider directly rather than seeded into
// localStorage, so these cases do not depend on the storage read.
function renderHeader(
  audience?: Audience,
  activePanel: 'logs' | 'audience' | null = null,
) {
  return render(
    <MemoryRouter>
      <AudienceProvider initialAudience={audience}>
        <ShellHeader
          navOpen={false}
          toggleNav={() => {}}
          startNewChat={() => {}}
          headerTitle=""
          activePanel={activePanel}
          onTogglePanel={() => {}}
          logsControlRef={{current: null}}
        />
      </AudienceProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => window.localStorage.clear());

it('shows Logs for the general audience only', () => {
  renderHeader('general');
  expect(screen.getByRole('button', {name: /Logs/i})).toBeInTheDocument();
  // No audience-specific control for the general audience.
  expect(
    screen.queryByRole('button', {name: /Feedback/i}),
  ).not.toBeInTheDocument();
});

it('shows the pilot Feedback control for sbi_ucd instead of Logs', () => {
  renderHeader('sbi_ucd');
  expect(screen.getByRole('button', {name: /Feedback/i})).toBeInTheDocument();
  // The audience control replaces Logs, rather than sitting beside it.
  expect(screen.queryByRole('button', {name: /Logs/i})).not.toBeInTheDocument();
});

it('sends google straight to the proposals, instead of Logs', () => {
  renderHeader('google');
  expect(
    screen.getByRole('link', {name: GOOGLE_PROPOSALS.label}),
  ).toHaveAttribute('href', '/proposals');
  expect(screen.queryByRole('button', {name: /Logs/i})).not.toBeInTheDocument();
});

it('navigates on the first click, with no panel in the way', () => {
  // The control replaced a popover, so the regression to guard is it
  // behaving like one again: a link that only opens something is a click
  // the reader has to spend before reaching what they asked for.
  renderHeader('google');
  const link = screen.getByRole('link', {name: GOOGLE_PROPOSALS.label});
  expect(link).not.toHaveAttribute('aria-expanded');
  expect(screen.queryByRole('group')).not.toBeInTheDocument();
});
