import {render} from '@testing-library/react';
import type {Report, ResearchOverview, RunWithSummary} from '@/api/runs';
import {ResearchOverviewView} from './run_detail_overview';

export function makeRun(
  overrides: Partial<RunWithSummary> = {},
): RunWithSummary {
  return {
    id: 'run-1',
    research_goal: 'Study pathway X',
    status: 'completed',
    config: {},
    created_at: 1_700_000_000,
    completed_at: 1_700_000_000 + 3 * 3600,
    ...overrides,
  } as unknown as RunWithSummary;
}

export function makeReport(overrides: Partial<Report['payload']> = {}): Report {
  return {
    id: 'rep-1',
    run_id: 'run-1',
    markdown_path: '',
    created_at: 1,
    payload: {
      research_goal: 'Study pathway X',
      provider: 'mock',
      leaderboard: [],
      ...overrides,
    },
  } as unknown as Report;
}

export function makeFullOverviewSection(): ResearchOverview['overview'] {
  return {
    summary: 'A synthesized summary of the research.',
    research_directions: [
      {
        title: 'Direction one',
        importance: 'It matters because X.',
        recent_findings: 'What is already known about direction one.',
        suggested_experiments: ['Experiment A', 'Experiment B'],
        sub_topics: [
          {
            title: 'Sub-topic one',
            why: 'Why sub-topic one matters.',
            what: 'What to investigate in sub-topic one.',
            specific_questions: ['Question A?', 'Question B?'],
          },
        ],
      },
      {
        title: 'Direction two (no experiments)',
        importance: 'It matters because Y.',
        suggested_experiments: [],
      },
    ],
  };
}

export function makeFullSpecificAims(): ResearchOverview['nih_specific_aims'] {
  return {
    disease_description: 'An introduction to the aims.',
    unmet_need: 'Nothing measures it yet.',
    proposed_solution: 'Do the thing, carefully.',
    aims: [
      {
        overarching_goal: 'Aim 1: Do the thing',
        hypothesis: 'Because reasons.',
        reasoning: 'Via this approach.',
      },
    ],
    pilot_evaluation: 'The impact statement.',
  };
}

type ResearchContacts = ResearchOverview['research_contacts'];

export function makeFullResearchContacts(): ResearchContacts {
  return [
    {
      candidate_id: 'author-1-1',
      name: 'Ada Researcher',
      expertise: 'Fibrosis mechanisms',
      justification: 'Authored a directly relevant analyzed paper.',
      source_id: 'PMID:123',
      source_title: 'A fibrosis study',
      source_url: 'https://pubmed.ncbi.nlm.nih.gov/123/',
      source: 'pubmed',
      research_direction: 'Direction one',
    },
  ];
}

export function makeFullReport(): Report {
  return makeReport({
    // Deliberately unequal: a run explores more ideas than it releases, and
    // the two counts drive different parts of the summary. Equal fixtures
    // let the lead stat read the released count without any test noticing.
    idea_count: 5,
    hypothesis_count: 2,
    verified_count: 1,
    evidence_count: 11,
    match_count: 3,
    idea_buckets: {
      high_potential: [
        {id: 'h1', title: 'Leaderboard idea', reason: 'Released.'},
      ],
      non_viable: [{id: 'h3', title: 'Rejected idea', reason: 'Contradicted.'}],
    },
    leaderboard: [
      {id: 'h1', title: 'Leaderboard idea', elo: 1735},
      {id: 'h2', title: 'Second idea', elo: 1600},
    ],
    research_overview: {
      overview: makeFullOverviewSection(),
      nih_specific_aims: makeFullSpecificAims(),
      research_contacts: makeFullResearchContacts(),
    },
  });
}

export function renderFullReport() {
  render(
    <ResearchOverviewView
      run={makeRun()}
      report={makeFullReport()}
      hypotheses={[]}
      matches={[]}
    />,
  );
}
