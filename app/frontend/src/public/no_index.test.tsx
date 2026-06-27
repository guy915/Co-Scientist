import {describe, it, expect} from 'vitest';
import {render, waitFor} from '@testing-library/react';
import {NoIndex} from './no_index';

describe('NoIndex', () => {
  // NoIndex renders nothing directly; it drives document head metadata via the
  // Seo effect, so assert on the document rather than the DOM tree.
  it('sets the document title to the page name suffixed with the site', async () => {
    render(<NoIndex title="Settings" />);
    await waitFor(() =>
      expect(document.title).toBe('Settings - AI Co-Scientist'),
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
