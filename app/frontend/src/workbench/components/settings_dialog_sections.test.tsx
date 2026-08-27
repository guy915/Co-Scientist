import {render, screen} from '@testing-library/react';
import {expect, it} from 'vitest';
import {HelpSection} from './settings_dialog_sections';

it('answers what the app is and how to start a run', () => {
  render(<HelpSection />);
  expect(screen.getByText('What is Co-Scientist?')).toBeInTheDocument();
  expect(screen.getByText('How do I start a run?')).toBeInTheDocument();
});

// The FAQ used to carry a "Are there keyboard shortcuts?" entry, because the
// two shortcuts it described had no other discoverable surface. Both are
// gone, and the FAQ is the one place a reader would look to find out that
// they exist -- documenting a binding the app no longer honors would be
// worse than saying nothing, so the entry has to go with them. See
// layout_no_shortcuts.test.tsx for the check that none came back.
it('promises no keyboard shortcuts', () => {
  render(<HelpSection />);
  expect(screen.queryByText(/keyboard shortcut/i)).toBeNull();
  expect(screen.queryByText(/arrow key/i)).toBeNull();
});
