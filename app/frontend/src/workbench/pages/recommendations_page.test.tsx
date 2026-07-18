import {render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';
import {RecommendationsPage} from './recommendations_page';

describe('RecommendationsPage', () => {
  it('renders the recommendations heading and points', () => {
    render(<RecommendationsPage />);
    expect(
      screen.getByRole('heading', {name: /Recommendations/i}),
    ).toBeInTheDocument();
    expect(screen.getAllByRole('listitem').length).toBeGreaterThan(0);
  });
});
