import {render, screen} from '@testing-library/react';
import {expect, it} from 'vitest';
import {ResearchOverviewView} from './run_detail_overview';
import {
  makeReport,
  makeRun,
  renderFullReport,
} from './run_detail_overview_test_support';

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
  expect(screen.getByText('Direction one')).toBeInTheDocument();
  expect(screen.getByText('It matters because X.')).toBeInTheDocument();
  expect(screen.getByText('Experiment A')).toBeInTheDocument();
  expect(screen.getByText('Experiment B')).toBeInTheDocument();
  // Second direction has no suggested experiments, so no list under it.
  expect(
    screen.getByText('Direction two (no experiments)'),
  ).toBeInTheDocument();
});

it('flattens malformed research directions instead of showing raw JSON', () => {
  // In production the model emits these fields in json_object mode with no
  // schema enforcement, so a string field can arrive as serialized JSON or an
  // object. The section must render readable text, never raw JSON.
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
  expect(screen.getByText('Delete relA - test tolerance')).toBeInTheDocument();
  // The JSON-array-string experiment is parsed into individual items.
  expect(screen.queryByText('["Assay A", "Assay B"]')).not.toBeInTheDocument();
  // No raw JSON braces leak into the rendered output.
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

  expect(screen.getByText('Targets tolerance - in vitro')).toBeInTheDocument();
  expect(screen.getByText('Guards against artefacts')).toBeInTheDocument();
  expect(screen.getByText('Biofilm metabolism')).toBeInTheDocument();
  expect(document.body.textContent).not.toContain('{"context"');
  expect(document.body.textContent).not.toContain('{"field"');
  expect(document.body.textContent).not.toContain('{"why"');
  // The source link keeps its real URL.
  expect(
    screen.getByRole('link', {name: 'Evidence: A biofilm study'}),
  ).toHaveAttribute('href', 'https://example.org/paper');
});

it('renders the specific aims and research contacts', () => {
  renderFullReport();

  expect(
    screen.getByRole('heading', {name: 'Specific aims'}),
  ).toBeInTheDocument();
  expect(screen.getByText('An introduction to the aims.')).toBeInTheDocument();
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
  expect(
    screen.getByRole('link', {name: 'Evidence: A fibrosis study'}),
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

it('still renders aims stored in the previous shape', () => {
  // Reports persist as the engine produced them, so runs that predate the
  // exemplar vocabulary keep introduction/aim/rationale/approach/impact.
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
  expect(screen.getByText('Knockdown in a matched model.')).toBeInTheDocument();
  expect(
    screen.getByText('A decision framework for the mechanism.'),
  ).toBeInTheDocument();
});
