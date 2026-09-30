import {fireEvent, render, screen} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {expect, it, vi} from 'vitest';
import {HelpSection} from './settings_dialog_sections';

// The FAQ moved out of Settings to the landing page under the chat home
// (home_landing_content.ts), so Help carries one link to it rather than a
// second copy that could drift. Its own checks live in home_landing.test.tsx.
it('links to the FAQ on the landing page and closes on the way', () => {
  const onNavigate = vi.fn();
  render(
    <MemoryRouter>
      <HelpSection onNavigate={onNavigate} />
    </MemoryRouter>,
  );
  const link = screen.getByRole('link', {name: 'Read the FAQ'});
  expect(link).toHaveAttribute('href', '/#faq');
  fireEvent.click(link);
  expect(onNavigate).toHaveBeenCalledOnce();
  expect(screen.queryByText('What is Co-Scientist?')).toBeNull();
});
