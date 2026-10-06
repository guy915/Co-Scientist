import {fireEvent, render, screen, within} from '@testing-library/react';
import {describe, expect, it} from 'vitest';
import type {Report, AgentInsights} from '@/api/runs';
import {LearningView} from './run_detail_learning';
import {ResearchOverviewView} from './run_detail_overview';
import {makeReport, makeRun} from './run_detail_overview_test_support';
import {AgentInsightsSection} from './run_detail_overview';

describe('run detail learning', () => {
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
      retracted: false,
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
      retracted: false,
    },
  ];

  // Non-adjacent references distinguish global numbering from per-topic
  // counters.
  const numberedEvidence = ['ev-a', 'ev-b', 'ev-c', 'ev-d'].map(
    (id, index) => ({
      id,
      title: `reference title ${index + 1}`,
      source: 'PubMed',
      url: '',
      authors: [],
      year: 2025,
      abstract: '',
      available: true,
      retracted: false,
    }),
  );

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

      expect(
        screen.getByText('synaptic pruning mechanisms'),
      ).toBeInTheDocument();
      expect(
        screen.queryByText('mitochondrial feedback in cold stress'),
      ).toBeNull();
    });
  });

  describe('LearningView unreachable sources (D18)', () => {
    const unreachable = {
      id: 'ev-gone',
      title: 'a source that never resolved',
      source: 'PubMed',
      url: 'https://example.test/gone',
      authors: ['A. Researcher'],
      year: 2025,
      abstract: '',
      available: false,
      retracted: false,
    };

    it('labels a retracted reference distinctly from a merely unreachable one', () => {
      render(
        <LearningView
          goal="goal"
          evidence={[{...unreachable, retracted: true}]}
        />,
      );

      const pill = screen.getByText('Retracted');
      expect(pill).toBeInTheDocument();
      expect(pill).toHaveAttribute('title', 'This source has been retracted');
      expect(screen.queryByText('Unavailable')).toBeNull();
      expect(screen.queryByRole('link', {name: 'Open'})).toBeNull();
    });
  });

  describe('LearningView supporting-reference numbering', () => {
    it('numbers citations by their place in the reference list', () => {
      const block = renderNumberedTopic(['ev-c', 'ev-a']);
      const links = within(block).getAllByRole('link');

      expect(links.map(link => link.textContent)).toEqual(['[1]', '[3]']);
      expect(links[1]).toHaveAttribute('href', '#reference-ev-c');
    });
  });
});

describe('run detail retrieval degraded', () => {
  // Empty literature retrieval is otherwise invisible in a seemingly complete
  // report.

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

  it('says what a run without any source lost, and what it had left', () => {
    renderWithReport({
      retrieval_degradation: {
        reason: 'mcp_unreachable',
        lost: ['literature_review', 'deep_research'],
        floor: 'none',
      },
    });

    expect(
      screen.getByText(/No literature source was reachable during this run/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/the literature review and follow-up research/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Nothing else was available to search/),
    ).toBeInTheDocument();
  });
});

describe('run detail insights', () => {
  function makeInsights(overrides: Partial<AgentInsights> = {}): AgentInsights {
    return {
      key_findings: ['Feedback is causal.'],
      uncertainties: [],
      contradictions: [],
      recommended_directions: [],
      next_experiments: [],
      ...overrides,
    };
  }

  it('renders each recommendation as its three named fields', () => {
    render(
      <AgentInsightsSection
        insights={makeInsights({
          recommended_directions: [
            {
              focus_area: 'Receptor pharmacology',
              recommendation: 'Measure binding directly by SPR.',
              justification: 'The claimed affinity is unproven.',
            },
          ],
        })}
      />,
    );

    expect(
      screen.getByRole('heading', {name: 'Recommended directions'}),
    ).toBeInTheDocument();
    expect(screen.getByText('Receptor pharmacology')).toBeInTheDocument();
    expect(
      screen.getByText('Measure binding directly by SPR.'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('The claimed affinity is unproven.'),
    ).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("{'focus_area'");
    expect(document.body.textContent).not.toContain('"focus_area"');
  });

  it('flags a meta-review that degraded to a fallback', () => {
    render(<AgentInsightsSection insights={makeInsights()} degraded />);

    expect(
      screen.getByText(
        'This section could not be generated after repeated attempts.',
      ),
    ).toBeInTheDocument();
  });
});
