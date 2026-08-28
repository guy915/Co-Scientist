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
  // "Direction one" also names the research-contact linkage line below, so
  // this asserts at least the direction heading exists rather than picking
  // one occurrence arbitrarily.
  expect(screen.getAllByText('Direction one').length).toBeGreaterThan(0);
  expect(screen.getByText('It matters because X.')).toBeInTheDocument();
  expect(screen.getByText('Experiment A')).toBeInTheDocument();
  expect(screen.getByText('Experiment B')).toBeInTheDocument();
  // Second direction has no suggested experiments, so no list under it.
  expect(
    screen.getByText('Direction two (no experiments)'),
  ).toBeInTheDocument();
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
  expect(screen.getByText('Question A?')).toBeInTheDocument();
  expect(screen.getByText('Question B?')).toBeInTheDocument();
  // Direction two carries neither field, and must not fall over.
  expect(
    screen.getByText('Direction two (no experiments)'),
  ).toBeInTheDocument();
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
  // MO-7: ties the contact back to the direction that surfaced them.
  // "Direction one" also names the research-direction heading above, so
  // this asserts both occurrences rather than picking one arbitrarily.
  expect(screen.getByText('Research direction:')).toBeInTheDocument();
  expect(screen.getAllByText('Direction one')).toHaveLength(2);
  expect(
    screen.getByRole('link', {name: 'Evidence: A fibrosis study'}),
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
  // research_overview_contacts.py:151 does `raw.get("research_direction")
  // or ""`, so an empty string is a legitimate, non-crash value here too --
  // it must render no label, not a label with nothing after it.
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
