import {render, screen} from '@testing-library/react';
import {expect, it, describe} from 'vitest';
import type {Hypothesis} from '@/api/runs';
import {makeHypothesis, makeMatch} from '@/test_fixtures';
import {ResearchOverviewView} from './run_detail_overview';
import {
  makeRun,
  makeReport,
  renderFullReport,
} from './run_detail_overview_test_support';

describe('run detail overview', () => {
  it('falls back to live data when there is no persisted report', async () => {
    const hypotheses: Hypothesis[] = [
      makeHypothesis({id: 'h1', title: 'Top idea', elo_rating: 1700}),
    ];
    render(
      <ResearchOverviewView
        run={makeRun()}
        report={null}
        hypotheses={hypotheses}
        matches={[makeMatch(1)]}
      />,
    );

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
    render(
      <ResearchOverviewView
        run={makeRun()}
        report={null}
        hypotheses={[]}
        matches={[]}
      />,
    );
    expect(
      screen.getByText('Tournament matches appear here once ranking begins.'),
    ).toBeInTheDocument();
    expect(screen.queryByText('Research directions')).not.toBeInTheDocument();
    expect(screen.queryByText('Specific aims')).not.toBeInTheDocument();
    expect(screen.queryByText('Winning ideas')).not.toBeInTheDocument();
  });

  it('renders an old saved report without a leaderboard', () => {
    render(
      <ResearchOverviewView
        run={makeRun()}
        report={{
          id: 'old-report',
          run_id: 'run-1',
          markdown_path: '',
          created_at: 1,
          payload: {},
        }}
        hypotheses={[makeHypothesis({id: 'h1', title: 'Saved idea'})]}
        matches={[]}
      />,
    );
    expect(screen.getByText('Saved idea')).toBeVisible();
  });
});

describe('run detail overview degraded', () => {
  const NOTICE = 'This section could not be generated after repeated attempts.';

  function renderWithReport(
    payloadOverrides: Parameters<typeof makeReport>[0],
  ) {
    render(
      <ResearchOverviewView
        run={makeRun()}
        report={makeReport(payloadOverrides)}
        hypotheses={[]}
        matches={[]}
      />,
    );
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

  it('keeps the in-flight placeholder when nothing degraded', () => {
    renderWithReport({research_overview: {}});

    expect(
      screen.getByText(/appears after Co-Scientist finishes/),
    ).toBeInTheDocument();
    expect(screen.queryByText(NOTICE)).not.toBeInTheDocument();
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
  it('omits intro/impact paragraphs when a specific aim lacks them', () => {
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
    render(
      <ResearchOverviewView
        run={makeRun()}
        report={report}
        hypotheses={[]}
        matches={[]}
      />,
    );
    expect(
      screen.getByText('Aim without surrounding copy'),
    ).toBeInTheDocument();
  });

  it('omits the duration clause on a zero or negative delta', () => {
    const report = makeReport({
      idea_count: 1,
      leaderboard: [{id: 'h1', title: 'Only idea', elo: 1500}],
    });
    render(
      <ResearchOverviewView
        run={makeRun({created_at: 1000, completed_at: 1000})}
        report={report}
        hypotheses={[]}
        matches={[]}
      />,
    );
    const stat = screen.getByText(/A total of 1 idea was explored/);
    expect(stat.textContent).not.toContain('over');
  });

  it('omits the duration and Elo clauses when no data is present', () => {
    const report = makeReport({idea_count: 1, leaderboard: []});
    render(
      <ResearchOverviewView
        run={null}
        report={report}
        hypotheses={[]}
        matches={[]}
      />,
    );
    const stat = screen.getByText(/A total of 1 idea was explored/);
    expect(stat.textContent).toBe('A total of 1 idea was explored.');
  });

  it('counts every idea explored, not just the released ones', () => {
    const report = makeReport({
      idea_count: 22,
      hypothesis_count: 2,
      leaderboard: [],
    });
    render(
      <ResearchOverviewView
        run={null}
        report={report}
        hypotheses={[]}
        matches={[]}
      />,
    );
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
    render(
      <ResearchOverviewView
        run={null}
        report={report}
        hypotheses={[]}
        matches={[]}
      />,
    );
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

  it('renders a recent-findings line and the nested sub-topics (MO-12, MO-1)', () => {
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

  it('omits recent findings and sub-topics for a direction stored before they existed', () => {
    const report = makeReport({
      research_overview: {
        overview: {
          research_directions: [
            {
              title: 'An old direction',
              importance: 'It still matters.',
              suggested_experiments: ['Experiment A'],
              // No recent_findings/sub_topics keys at all -- the shape a
              // report persisted before MO-1/MO-12 landed still carries.
            },
          ],
        },
      },
    } as unknown as Parameters<typeof makeReport>[0]);

    render(
      <ResearchOverviewView
        run={makeRun()}
        report={report}
        hypotheses={[]}
        matches={[]}
      />,
    );

    expect(screen.getByText('An old direction')).toBeInTheDocument();
    expect(screen.getByText('It still matters.')).toBeInTheDocument();
    expect(screen.queryByText('Recent findings:')).not.toBeInTheDocument();
    expect(screen.queryByText('Why:')).not.toBeInTheDocument();
    expect(screen.queryByText('What:')).not.toBeInTheDocument();
    expect(screen.queryByText('Example idea:')).not.toBeInTheDocument();
    expect(
      screen.queryByText('We will be focusing on these research directions:'),
    ).not.toBeInTheDocument();
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

    render(
      <ResearchOverviewView
        run={makeRun()}
        report={report}
        hypotheses={[]}
        matches={[]}
      />,
    );

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

    render(
      <ResearchOverviewView
        run={makeRun()}
        report={report}
        hypotheses={[]}
        matches={[]}
      />,
    );

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

    render(
      <ResearchOverviewView
        run={makeRun()}
        report={report}
        hypotheses={[]}
        matches={[]}
      />,
    );

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

    render(
      <ResearchOverviewView
        run={makeRun()}
        report={report}
        hypotheses={[]}
        matches={[]}
      />,
    );

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

  it('omits the research-direction line for a contact stored before it existed', () => {
    const report = makeReport({
      research_overview: {
        research_contacts: [
          {
            candidate_id: 'author-1-1',
            name: 'Ada Researcher',
            expertise: 'Fibrosis mechanisms',
            justification: 'Authored a directly relevant analyzed paper.',
            source_title: 'A fibrosis study',
            source_url: 'https://pubmed.ncbi.nlm.nih.gov/123/',
            source: 'pubmed',
            // No research_direction key at all -- the shape a report
            // persisted before MO-7 landed still carries.
          },
        ],
      },
    } as unknown as Parameters<typeof makeReport>[0]);

    render(
      <ResearchOverviewView
        run={makeRun()}
        report={report}
        hypotheses={[]}
        matches={[]}
      />,
    );

    expect(screen.getByText('Ada Researcher')).toBeInTheDocument();
    expect(screen.queryByText('Research direction:')).not.toBeInTheDocument();
  });

  it('omits the research-direction line when the model returns it empty', () => {
    const report = makeReport({
      research_overview: {
        research_contacts: [
          {
            candidate_id: 'author-1-1',
            name: 'Ada Researcher',
            expertise: 'Fibrosis mechanisms',
            justification: 'Authored a directly relevant analyzed paper.',
            source_title: 'A fibrosis study',
            source_url: 'https://pubmed.ncbi.nlm.nih.gov/123/',
            source: 'pubmed',
            research_direction: '',
          },
        ],
      },
    } as unknown as Parameters<typeof makeReport>[0]);

    render(
      <ResearchOverviewView
        run={makeRun()}
        report={report}
        hypotheses={[]}
        matches={[]}
      />,
    );

    expect(screen.getByText('Ada Researcher')).toBeInTheDocument();
    expect(screen.queryByText('Research direction:')).not.toBeInTheDocument();
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

  it('still renders aims stored in the previous shape', () => {
    // Persisted reports may retain earlier
    // introduction/aim/rationale/approach/impact fields.
    const report = makeReport({
      research_overview: {
        nih_specific_aims: {
          introduction: 'Significance and the gap.',
          aims: [
            {
              aim: 'Aim 1: Establish the baseline.',
              rationale: 'Nothing else measures it.',
              approach: 'Knockdown in a matched model.',
            },
          ],
          impact: 'A decision framework for the mechanism.',
        },
      },
    } as unknown as Parameters<typeof makeReport>[0]);

    render(
      <ResearchOverviewView
        run={makeRun()}
        report={report}
        hypotheses={[]}
        matches={[]}
      />,
    );

    expect(screen.getByText('Significance and the gap.')).toBeInTheDocument();
    expect(
      screen.getByText('Aim 1: Establish the baseline.'),
    ).toBeInTheDocument();
    expect(screen.getByText('Nothing else measures it.')).toBeInTheDocument();
    expect(
      screen.getByText('Knockdown in a matched model.'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('A decision framework for the mechanism.'),
    ).toBeInTheDocument();
  });
});
