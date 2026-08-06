import {render, screen} from '@testing-library/react';
import {expect, it} from 'vitest';
import {HelpSection} from './settings_dialog_sections';

// The global keyboard shortcuts (g n -> home, arrow-key tab cycling on a
// run's report page) had no discoverable surface anywhere in the app; the
// Help FAQ is their documented home.
it('documents the keyboard shortcuts in the Help FAQ', () => {
  render(<HelpSection />);
  expect(screen.getByText('Are there keyboard shortcuts?')).toBeInTheDocument();
  expect(screen.getByText(/Press g then n/)).toBeInTheDocument();
});
