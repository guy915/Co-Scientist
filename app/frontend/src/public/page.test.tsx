import {describe, it, expect} from 'vitest';
import {render, waitFor, screen} from '@testing-library/react';
import {NoIndex, NotFoundPage} from './page';
import {MemoryRouter} from 'react-router-dom';

describe('no index', () => {
  describe('NoIndex', () => {
    // NoIndex renders nothing directly; it drives document head metadata via
    // its effect, so assert on the document rather than the DOM tree.
    it('sets the document title to the page name plus the site', async () => {
      render(<NoIndex title="Settings" />);
      await waitFor(() =>
        expect(document.title).toBe('Settings - Co-Scientist'),
      );
    });

    it('marks the page as noindex via the robots meta tag', async () => {
      render(<NoIndex title="Private" />);
      await waitFor(() => {
        const robots = document.head.querySelector('meta[name="robots"]');
        expect(robots).not.toBeNull();
        expect(robots).toHaveAttribute('content', 'noindex, nofollow');
      });
    });
  });
});

describe('not found page', () => {
  describe('NotFoundPage', () => {
    it('renders the 404 heading and message', () => {
      render(
        <MemoryRouter>
          <NotFoundPage />
        </MemoryRouter>,
      );
      expect(
        screen.getByRole('heading', {name: 'Page not found'}),
      ).toBeInTheDocument();
      expect(screen.getByText('404')).toBeInTheDocument();
      expect(
        screen.getByText('The page you requested does not exist.'),
      ).toBeInTheDocument();
    });

    it('renders the home call-to-action link', () => {
      render(
        <MemoryRouter>
          <NotFoundPage />
        </MemoryRouter>,
      );
      expect(screen.getByRole('link', {name: 'Return home'})).toHaveAttribute(
        'href',
        '/',
      );
      expect(screen.getAllByRole('link')).toHaveLength(1);
    });
  });
});
