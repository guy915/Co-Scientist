import {render, screen, waitFor} from '@testing-library/react';
import {beforeEach, describe, expect, it, vi} from 'vitest';
import type {DiscoveryReportPayload, Report} from '@/api/runs';
import {DiscoveryReportView} from './run_detail_discovery_report';

const fetchReportMarkdown = vi.fn();
vi.mock('@/api/runs', async importOriginal => ({
  ...(await importOriginal<typeof import('@/api/runs')>()),
  fetchReportMarkdown: (id: string) => fetchReportMarkdown(id),
}));

function payloadWith(
  overrides: Partial<DiscoveryReportPayload> = {},
): DiscoveryReportPayload {
  return {
    report_kind: 'discovery',
    research_goal: 'beat the baseline',
    provider: 'mock',
    objectives: [{metric: 'score', direction: 'maximize'}],
    variant_count: 12,
    scored_count: 9,
    generation_count: 4,
    niches_occupied: 5,
    niche_evenness: 0.9,
    best_variant_id: 'v7',
    best_fitness: 8.25,
    ...overrides,
  };
}

const REPORT = {id: 'rep1', run_id: 'r1'} as Report;

// A slice of what `discovery_report.build_markdown` actually emits. The
// two sections that carry the finding are pipe tables, so a stub of
// prose alone would not exercise the renderer that has to draw them.
const REPORT_MARKDOWN = [
  '# beat the baseline',
  '',
  '## Result',
  '',
  'Attempt 7 scored 8.25 via `rewrite`.',
  '',
  '## Every attempt',
  '',
  '| # | Change | Outcome | Score | Notes |',
  '|---|---|---|---|---|',
  '| 1 | seed | scored | 3.0 |  |',
  '| 7 | rewrite | scored | 8.25 | best so far |',
].join('\n');

describe('DiscoveryReportView', () => {
  beforeEach(() => {
    fetchReportMarkdown.mockReset();
    fetchReportMarkdown.mockResolvedValue(REPORT_MARKDOWN);
  });

  it('reports the attempts and the score the run reached', async () => {
    render(<DiscoveryReportView report={REPORT} payload={payloadWith()} />);
    expect(screen.getByText('12')).toBeInTheDocument();
    expect(screen.getByText('8.25')).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByText(/Attempt 7 scored/)).toBeInTheDocument(),
    );
  });

  it('draws the attempt table rather than leaving pipe soup', async () => {
    // The sections that carry the finding are markdown tables, so the
    // renderer has to be one that draws them.
    render(<DiscoveryReportView report={REPORT} payload={payloadWith()} />);
    await waitFor(() => expect(screen.getByRole('table')).toBeInTheDocument());
    expect(screen.getAllByRole('row')).toHaveLength(3);
    expect(screen.queryByText(/\|---\|/)).not.toBeInTheDocument();
  });

  it('prints the goal once, not once per source of it', async () => {
    // The body opens with the goal as an H1 because report.md is also
    // served standalone; the tab already prints it above.
    render(<DiscoveryReportView report={REPORT} payload={payloadWith()} />);
    await waitFor(() => expect(screen.getByRole('table')).toBeInTheDocument());
    expect(screen.getAllByText('beat the baseline')).toHaveLength(1);
  });

  it('says when a run spread unevenly rather than only counting cells', async () => {
    // Five cells with everything piled into one reads as thorough
    // unless the evenness is spoken.
    render(
      <DiscoveryReportView
        report={REPORT}
        payload={payloadWith({niche_evenness: 0.2})}
      />,
    );
    expect(screen.getByText('5, uneven')).toBeInTheDocument();
  });

  it('reads a minimized metric in its own units', async () => {
    // Stored sign-corrected, so 1.9 seconds is held as -1.9. Printed
    // straight it contradicts both the report body and the plot.
    render(
      <DiscoveryReportView
        report={REPORT}
        payload={payloadWith({
          objectives: [{metric: 'seconds', direction: 'minimize'}],
          best_fitness: -1.9,
        })}
      />,
    );
    expect(screen.getByText('1.9')).toBeInTheDocument();
  });

  it('renders an unscored run without inventing a zero', async () => {
    // No score is not a score of zero, and must not render as one.
    render(
      <DiscoveryReportView
        report={REPORT}
        payload={payloadWith({best_fitness: null, scored_count: 0})}
      />,
    );
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('still shows the stats when the markdown cannot be fetched', async () => {
    fetchReportMarkdown.mockRejectedValue(new Error('offline'));
    render(<DiscoveryReportView report={REPORT} payload={payloadWith()} />);
    await waitFor(() => expect(fetchReportMarkdown).toHaveBeenCalled());
    expect(screen.getByText('12')).toBeInTheDocument();
  });
});
