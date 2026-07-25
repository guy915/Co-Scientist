import {fireEvent, render, screen, within} from '@testing-library/react';
import {describe, expect, it} from 'vitest';
import {type Report} from '@/api/runs';
import {LearningView} from './run_detail_learning';

const evidence = [
  {
    id: 'ev-1',
    title: 'mitochondrial feedback in cold stress',
    source: 'PubMed',
    url: 'https://example.test/pubmed',
    authors: ['A. Researcher', 'B. Scientist'],
    year: 2025,
    abstract:
      'BACKGROUND: Cold stress changes glucose homeostasis. METHODS: Cells ' +
      'were profiled with mitochondrial assays.',
    available: true,
  },
  {
    id: 'ev-2',
    title: 'synaptic pruning mechanisms',
    source: 'Preprint',
    url: '',
    authors: ['C. Author'],
    year: null,
    abstract: 'Microglia remodel synapses during neuroinflammation.',
    available: true,
  },
];

// Four references so a topic can cite non-adjacent positions, which is what
// distinguishes real reference numbers from a per-topic 1..N counter.
const numberedEvidence = ['ev-a', 'ev-b', 'ev-c', 'ev-d'].map((id, index) => ({
  id,
  title: `reference title ${index + 1}`,
  source: 'PubMed',
  url: '',
  authors: [],
  year: 2025,
  abstract: '',
  available: true,
}));

function reportCiting(referenceIds: string[]): Report {
  return {
    id: 'report-1',
    run_id: 'run-1',
    markdown_path: '',
    created_at: 0,
    payload: {
      research_goal: 'goal',
      provider: 'engine',
      leaderboard: [],
      knowledge_base: [
        {
          id: 'topic-1',
          title: 'topic title',
          summary: 'topic summary',
          detail: 'topic detail',
          reference_ids: referenceIds,
        },
      ],
    },
  } as Report;
}

function renderNumberedTopic(referenceIds: string[]) {
  render(
    <LearningView
      goal="goal"
      evidence={numberedEvidence}
      report={reportCiting(referenceIds)}
    />,
  );
  fireEvent.click(screen.getByRole('button', {name: /Show more/i}));
  return screen.getByText('Supporting references:').parentElement!;
}

describe('LearningView', () => {
  it('renders learning sections, detail, and searchable refs', () => {
    render(
      <LearningView
        goal="Investigate glucose homeostasis under cold stress."
        evidence={evidence}
      />,
    );

    expect(
      screen.getByRole('heading', {name: 'Knowledge Base'}),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('heading', {
        name: 'Mitochondrial Feedback in Cold Stress',
      }),
    ).toBeInTheDocument();
    expect(screen.getByText('Background')).toBeInTheDocument();

    const openLink = screen.getByRole('link', {name: 'Open'});
    expect(openLink).toHaveAttribute('href', 'https://example.test/pubmed');
    expect(openLink).toHaveClass('reference-open-pill', 'rounded-full');

    fireEvent.click(screen.getAllByRole('button', {name: /Show more/i})[0]);

    expect(
      screen.getByText(/Source context: PubMed, 2025/),
    ).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Search references'), {
      target: {value: 'synaptic'},
    });

    expect(screen.getByText('synaptic pruning mechanisms')).toBeInTheDocument();
    expect(
      screen.queryByText('mitochondrial feedback in cold stress'),
    ).toBeNull();
  });
});

describe('LearningView supporting-reference numbering', () => {
  it('numbers citations by their place in the reference list', () => {
    const block = renderNumberedTopic(['ev-c', 'ev-a']);
    const links = within(block).getAllByRole('link');

    expect(links.map(link => link.textContent)).toEqual(['[1]', '[3]']);
    expect(links[1]).toHaveAttribute('href', '#reference-ev-c');
  });

  it('keeps citation numbers stable while the list is searched', () => {
    const block = renderNumberedTopic(['ev-d']);
    fireEvent.change(screen.getByLabelText('Search references'), {
      target: {value: 'reference title 4'},
    });

    expect(within(block).getByRole('link').textContent).toBe('[4]');
    expect(screen.getByText('[4]', {selector: 'span'})).toBeInTheDocument();
  });

  it('omits citations that resolve to no reference', () => {
    const block = renderNumberedTopic(['ev-b', 'ev-missing']);

    expect(within(block).getAllByRole('link')).toHaveLength(1);
    expect(within(block).getByRole('link').textContent).toBe('[2]');
  });
});
