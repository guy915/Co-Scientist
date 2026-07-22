import {render, screen} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {beforeEach, expect, it} from 'vitest';
import {type Audience, AudienceProvider} from './audience_context';
import {GOOGLE_NOTE} from './audience_content';
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

it('shows the team control for google instead of Logs', () => {
  renderHeader('google');
  expect(
    screen.getByRole('button', {name: GOOGLE_NOTE.label}),
  ).toBeInTheDocument();
  expect(screen.queryByRole('button', {name: /Logs/i})).not.toBeInTheDocument();
});

it('offers the note, the site, and a way to reply', () => {
  renderHeader('google', 'audience');
  expect(
    screen.getByRole('link', {name: GOOGLE_NOTE.linkLabel}),
  ).toHaveAttribute('href', '/proposals');
  // Both leave the app, so both open in their own tab.
  for (const [label, href] of [
    [GOOGLE_NOTE.aboutLabel, GOOGLE_NOTE.aboutUrl],
    [GOOGLE_NOTE.contactLabel, GOOGLE_NOTE.contactUrl],
  ]) {
    const link = screen.getByRole('link', {name: label});
    expect(link).toHaveAttribute('href', href);
    expect(link).toHaveAttribute('target', '_blank');
  }
});

it('addresses the reply to the maintainer with a subject', () => {
  const url = new URL(GOOGLE_NOTE.contactUrl);
  expect(url.searchParams.get('to')).toBe('guybarel2006@gmail.com');
  expect(url.searchParams.get('su')).toBeTruthy();
});
