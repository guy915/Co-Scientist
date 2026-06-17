import {describe, it, expect} from 'vitest';
import {render, screen} from '@testing-library/react';
import {RunStatusPill} from './RunStatusPill';

describe('RunStatusPill', () => {
  it('renders the label for a known status', () => {
    render(<RunStatusPill status="running" />);
    expect(screen.getByText('Running')).toBeInTheDocument();
  });

  it('renders the safety label for the blocked status', () => {
    render(<RunStatusPill status="blocked" />);
    expect(screen.getByText('Blocked (safety)')).toBeInTheDocument();
  });
});
