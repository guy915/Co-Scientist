import {screen} from '@testing-library/react';
import {expect, it, describe} from 'vitest';
import type {Hypothesis} from '@/api/runs';
import {makeHypothesis, makeMatch} from '@/test_fixtures';
import {
  makeRun,
  renderOverview,
  makeReport,
  renderFullReport,
} from './run_detail_overview_test_support';

describe('run detail overview', () => {
  it('falls back to live data when there is no persisted report', async () => {
    const hypotheses: Hypothesis[] = [
      makeHypothesis({id: 'h1', title: 'Top idea', elo_rating: 1700}),
    ];
    renderOverview({hypotheses, matches: [makeMatch(1)]});

    expect(
      screen.getByText(
        'The research overview appears after Co-Scientist finishes the final ' +
          'synthesis step.',
      ),
    ).toBeInTheDocument();
    expect(screen.getByText('Top idea')).toBeInTheDocument();
    expect(
      screen.getByText('1 tournament matches have been recorded for this run.'),
    ).toBeInTheDocument();
  });

  it('shows the pre-synthesis placeholders when there is no data', () => {
    renderOverview();
    expect(
      screen.getByText('Tournament matches appear here once ranking begins.'),
    ).toBeInTheDocument();
    expect(screen.queryByText('Research directions')).not.toBeInTheDocument();
    expect(screen.queryByText('Specific aims')).not.toBeInTheDocument();
    expect(screen.queryByText('Winning ideas')).not.toBeInTheDocument();
  });
});

describe('run detail overview degraded', () => {
  const NOTICE = 'This section could not be generated after repeated attempts.';

  function renderWithReport(
    payloadOverrides: Parameters<typeof makeReport>[0],
  ) {
    renderOverview({report: makeReport(payloadOverrides)});
  }

  it('labels a degraded research overview instead of the in-flight promise', () => {
    renderWithReport({
      degraded_sections: ['research_overview'],
      research_overview: {},
    });

    expect(screen.getByText(NOTICE)).toBeInTheDocument();
    expect(
      screen.queryByText(/appears after Co-Scientist finishes/),
    ).not.toBeInTheDocument();
  });

  it('flags agent insights when the meta-review degraded', () => {
    renderWithReport({degraded_sections: ['meta_review']});

    expect(
      screen.getByRole('heading', {name: 'Agent Insights'}),
    ).toBeInTheDocument();
    expect(screen.getByText(NOTICE)).toBeInTheDocument();
  });

  it('prefers real overview content over the notice when both exist', () => {
    renderWithReport({
      degraded_sections: ['research_overview'],
      research_overview: {overview: {summary: 'A partial synthesis.'}},
    });

    expect(screen.getByText('A partial synthesis.')).toBeInTheDocument();
    expect(screen.queryByText(NOTICE)).not.toBeInTheDocument();
  });
});

describe('run detail overview stat line', () => {
  it('renders current aim fields without surrounding paragraphs', () => {
    const report = makeReport({
      research_overview: {
        nih_specific_aims: {
          aims: [
            {
              overarching_goal: 'Aim without surrounding copy',
              hypothesis: 'R',
              reasoning: 'A',
            },
          ],
        },
      },
    });
    renderOverview({report});
    expect(
      screen.getByText('Aim without surrounding copy'),
    ).toBeInTheDocument();
  });

  it('omits the duration clause on a zero or negative delta', () => {
    const report = makeReport({
      idea_count: 1,
      leaderboard: [{id: 'h1', title: 'Only idea', elo: 1500}],
    });
    renderOverview({
      run: makeRun({created_at: 1000, completed_at: 1000}),
      report,
    });
    const stat = screen.getByText(/A total of 1 idea was explored/);
    expect(stat.textContent).not.toContain('over');
  });

  it('counts every idea explored, not just the released ones', () => {
    const report = makeReport({
      idea_count: 22,
      hypothesis_count: 2,
      leaderboard: [],
    });
    renderOverview({run: null, report});
    expect(
      screen.getByText('A total of 22 ideas were explored.'),
    ).toBeInTheDocument();
  });

  it('reports verified ideas separately from high-potential ones', () => {
    const report = makeReport({
      verified_count: 0,
      idea_buckets: {
        high_potential: [
          {id: 'h1', title: 'Released one', reason: 'Released.'},
          {id: 'h2', title: 'Released two', reason: 'Released.'},
        ],
        non_viable: [],
      },
    });
    renderOverview({run: null, report});
    const tile = screen.getByText('Verified ideas').closest('div');
    expect(tile?.textContent).toBe('Verified ideas0');
    expect(screen.getByText('High Potential').closest('div')?.textContent).toBe(
      'High Potential2',
    );
  });
});

describe('run detail overview sections', () => {
  it('renders the synthesized summary and idea buckets from the report', () => {
    renderFullReport();

    expect(
      screen.getByText('A synthesized summary of the research.'),
    ).toBeInTheDocument();
    expect(screen.getByText('High Potential')).toBeInTheDocument();
    expect(screen.getByText('Non-Viable')).toBeInTheDocument();
    expect(screen.getByText('Verified ideas')).toBeInTheDocument();
    expect(screen.getByText('Sources Analyzed')).toBeInTheDocument();
    expect(screen.getByText('11')).toBeInTheDocument();
  });

  it('renders the research directions with their suggested experiments', () => {
    renderFullReport();

    expect(
      screen.getByRole('heading', {name: 'Research directions'}),
    ).toBeInTheDocument();
    // Direction titles appear in preview bullets and detail headings; queries
    // must allow duplicates.
    expect(
      screen.getByText('We will be focusing on these research directions:'),
    ).toBeInTheDocument();
    expect(screen.getAllByText('Direction one').length).toBeGreaterThan(0);
    expect(screen.getByText('It matters because X.')).toBeInTheDocument();
    expect(screen.getByText('Experiment A')).toBeInTheDocument();
    expect(screen.getByText('Experiment B')).toBeInTheDocument();
    expect(
      screen.getAllByText('Direction two (no experiments)').length,
    ).toBeGreaterThan(0);
  });

  it('renders recent findings and nested sub-topics', () => {
    renderFullReport();

    expect(screen.getByText('Recent findings:')).toBeInTheDocument();
    expect(
      screen.getByText('What is already known about direction one.'),
    ).toBeInTheDocument();
    expect(screen.getByText('Sub-topic one')).toBeInTheDocument();
    expect(screen.getByText('Why:')).toBeInTheDocument();
    expect(screen.getByText('Why sub-topic one matters.')).toBeInTheDocument();
    expect(screen.getByText('What:')).toBeInTheDocument();
    expect(
      screen.getByText('What to investigate in sub-topic one.'),
    ).toBeInTheDocument();
    expect(screen.getByText('Example idea:')).toBeInTheDocument();
    expect(
      screen.getByText('One worked example for sub-topic one.'),
    ).toBeInTheDocument();
    expect(screen.getByText('Question A?')).toBeInTheDocument();
    expect(screen.getByText('Question B?')).toBeInTheDocument();
    expect(
      screen.getAllByText('Direction two (no experiments)').length,
    ).toBeGreaterThan(0);
  });

  it('gates the directions preview on at least two named directions', () => {
    const report = makeReport({
      research_overview: {
        overview: {
          research_directions: [
            {title: 'Named direction'},
            {importance: 'Untitled but has content.'},
          ],
        },
      },
    } as unknown as Parameters<typeof makeReport>[0]);

    renderOverview({report});

    expect(screen.getByText('Named direction')).toBeInTheDocument();
    expect(screen.getByText('Untitled but has content.')).toBeInTheDocument();
    expect(
      screen.queryByText('We will be focusing on these research directions:'),
    ).not.toBeInTheDocument();
  });

  it('previews two named directions ahead of the full per-direction detail', () => {
    const report = makeReport({
      research_overview: {
        overview: {
          research_directions: [
            {title: 'First direction'},
            {title: 'Second direction'},
          ],
        },
      },
    } as unknown as Parameters<typeof makeReport>[0]);

    renderOverview({report});

    expect(
      screen.getByText('We will be focusing on these research directions:'),
    ).toBeInTheDocument();
    expect(screen.getAllByText('First direction').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Second direction').length).toBeGreaterThan(0);
  });

  it('flattens malformed research directions instead of showing raw JSON', () => {
    // json_object mode permits object or serialized-string fields without
    // schema enforcement.
    const report = makeReport({
      research_overview: {
        overview: {
          summary: 'A synthesized summary of the research.',
          research_directions: [
            {
              title: 'Targeting the stringent response',
              importance:
                '{"significance": "Guards against tolerance", "gap": "None"}',
              suggested_experiments: [
                {experiment: 'Delete relA', rationale: 'test tolerance'},
                '["Assay A", "Assay B"]',
              ],
            },
          ],
        },
      },
    } as unknown as Parameters<typeof makeReport>[0]);

    renderOverview({report});

    expect(
      screen.getByText('Targeting the stringent response'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('Guards against tolerance - None'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('Delete relA - test tolerance'),
    ).toBeInTheDocument();
    expect(
      screen.queryByText('["Assay A", "Assay B"]'),
    ).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain('{"significance"');
    expect(document.body.textContent).not.toContain('"experiment"');
  });

  it('flattens malformed aims and contacts instead of showing raw JSON', () => {
    const report = makeReport({
      research_overview: {
        nih_specific_aims: {
          disease_description:
            '{"context": "Targets tolerance", "scope": "in vitro"}',
          aims: [
            {
              overarching_goal: 'Aim 1: Delete relA',
              hypothesis: {why: 'Guards against artefacts'},
              reasoning: 'Static and flow-cell assays.',
            },
          ],
          pilot_evaluation: 'Converts the lead hypothesis into a program.',
        },
        research_contacts: [
          {
            candidate_id: 'author-1-1',
            name: 'Ada Researcher',
            expertise: '{"field": "Biofilm metabolism"}',
            justification: 'Authored an analyzed paper.',
            source_title: 'A biofilm study',
            source_url: 'https://example.org/paper',
            source: 'pubmed',
          },
        ],
      },
    } as unknown as Parameters<typeof makeReport>[0]);

    renderOverview({report});

    expect(
      screen.getByText('Targets tolerance - in vitro'),
    ).toBeInTheDocument();
    expect(screen.getByText('Guards against artefacts')).toBeInTheDocument();
    expect(screen.getByText('Biofilm metabolism')).toBeInTheDocument();
    expect(document.body.textContent).not.toContain('{"context"');
    expect(document.body.textContent).not.toContain('{"field"');
    expect(document.body.textContent).not.toContain('{"why"');
    expect(
      screen.getByRole('link', {name: 'Supporting article: A biofilm study'}),
    ).toHaveAttribute('href', 'https://example.org/paper');
  });

  it('renders the specific aims and research contacts', () => {
    renderFullReport();

    expect(
      screen.getByRole('heading', {name: 'Specific aims', level: 3}),
    ).toBeInTheDocument();
    expect(
      screen.getByText('An introduction to the aims.'),
    ).toBeInTheDocument();
    // Section and aim headings share a phrase; distinguish them by heading
    // level.
    expect(
      screen.getByRole('heading', {name: 'Specific Aims 1', level: 4}),
    ).toBeInTheDocument();
    expect(screen.getByText('Overarching goal:')).toBeInTheDocument();
    expect(screen.getByText('Aim 1: Do the thing')).toBeInTheDocument();
    expect(screen.getByText('Hypothesis:')).toBeInTheDocument();
    expect(screen.getByText('Because reasons.')).toBeInTheDocument();
    expect(screen.getByText('Reasoning:')).toBeInTheDocument();
    expect(screen.getByText('Via this approach.')).toBeInTheDocument();
    expect(screen.getByText('The impact statement.')).toBeInTheDocument();
    expect(
      screen.getByRole('heading', {name: 'Research contacts'}),
    ).toBeInTheDocument();
    expect(screen.getByText('Ada Researcher')).toBeInTheDocument();
    expect(screen.getByText('Justification:')).toBeInTheDocument();
    // Preview bullets and contact linkage can repeat direction names.
    expect(screen.getByText('Research direction:')).toBeInTheDocument();
    expect(screen.getAllByText('Direction one').length).toBeGreaterThan(0);
    expect(
      screen.getByRole('link', {name: 'Supporting article: A fibrosis study'}),
    ).toHaveAttribute('href', 'https://pubmed.ncbi.nlm.nih.gov/123/');
  });

  it('renders the winning-ideas leaderboard and closing stats', () => {
    renderFullReport();

    expect(
      screen.getByRole('heading', {name: 'Winning ideas'}),
    ).toBeInTheDocument();
    expect(screen.getByText('Leaderboard idea')).toBeInTheDocument();
    expect(screen.getByText('Elo rating: 1735')).toBeInTheDocument();

    expect(
      screen.getByText(
        new RegExp(
          'A total of 5 ideas were explored over 3 hours with the highest ' +
            'Elo rating of 1735 points and a total of 3 matches were ' +
            'played\\.',
        ),
      ),
    ).toBeInTheDocument();
  });
});
