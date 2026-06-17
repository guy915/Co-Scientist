import {describe, it, expect, vi, beforeEach, beforeAll} from 'vitest';
import {render, screen} from '@testing-library/react';
import {userEvent} from '@testing-library/user-event';
import {ThemeProvider} from '../ThemeContext';
import {ThemeToggle} from './ThemeToggle';

// ThemeProvider applies the MD3 palette via material-color-utilities, which
// fails to resolve in jsdom. Stub it so the provider renders.
vi.mock('@/lib/theme', () => ({applyMd3Theme: vi.fn()}));

beforeAll(() => {
  // jsdom does not implement matchMedia, which ThemeProvider reads on mount.
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }),
  });
});

describe('ThemeToggle', () => {
  beforeEach(() => {
    // The toggle persists the chosen mode; reset so each test starts in light.
    localStorage.removeItem('coscientist-theme');
  });

  it('renders the toggle with the switch-to-dark label by default', () => {
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    );
    expect(screen.getByLabelText('Switch to dark mode')).toBeInTheDocument();
  });

  it('flips the label when clicked', async () => {
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    );
    await userEvent.click(screen.getByLabelText('Switch to dark mode'));
    expect(screen.getByLabelText('Switch to light mode')).toBeInTheDocument();
  });
});
