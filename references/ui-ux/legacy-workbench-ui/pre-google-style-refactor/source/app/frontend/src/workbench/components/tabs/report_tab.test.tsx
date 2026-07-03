import {describe, it, expect} from 'vitest';
import {render, screen} from '@testing-library/react';
import {ReportTab} from './report_tab';

describe('ReportTab', () => {
  it('shows the pending message when no report exists yet', () => {
    // The report=null branch renders without any markdown fetch.
    render(<ReportTab runId="r1" report={null} safety={[]} />);
    expect(
      screen.getByText('The report appears once the workflow finishes.'),
    ).toBeInTheDocument();
  });
});
