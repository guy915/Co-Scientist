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

  // Evidence titles carrying scientific terms whose casing must survive
  // title-casing verbatim: an all-caps abbreviation glued to lowercase letters
  // ("mRNA") and a Greek-letter prefix ("α-synuclein") that journals set
  // lowercase, both of which naive per-word capitalization mangles.
  const scientificTermEvidence = [
    {
      id: 'ev-mrna',
      title: 'mRNA expression during cold stress',
      source: 'PubMed',
      url: '',
      authors: [],
      year: 2025,
      abstract: '',
      available: true,
      retracted: false,
    },
    {
      id: 'ev-greek',
      title: 'α-synuclein aggregation in neurons',
      source: 'PubMed',
      url: '',
      authors: [],
      year: 2025,
      abstract: '',
      available: true,
      retracted: false,
    },
  ];

  // Four references so a topic can cite non-adjacent positions, which is what
  // distinguishes real reference numbers from a per-topic 1..N counter.
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

  describe('LearningView section title capitalization', () => {
    it('keeps scientific-term casing intact while title-casing the rest', () => {
      render(<LearningView goal="goal" evidence={scientificTermEvidence} />);

      expect(
        screen.getByRole('heading', {
          name: 'mRNA Expression During Cold Stress',
        }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole('heading', {
          name: 'α-synuclein Aggregation in Neurons',
        }),
      ).toBeInTheDocument();
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

    it('labels an unavailable reference instead of offering to open it', () => {
      render(<LearningView goal="goal" evidence={[unreachable]} />);

      const pill = screen.getByText('Unavailable');
      expect(pill).toBeInTheDocument();
      expect(pill).toHaveAttribute(
        'title',
        'The full source could not be reached when this evidence was gathered',
      );
      // The row still carries a url, but an unreachable source must not render
      // the normal "Open" action beside it.
      expect(screen.queryByRole('link', {name: 'Open'})).toBeNull();
    });

    it('keeps the Open action for a reachable reference', () => {
      render(
        <LearningView
          goal="goal"
          evidence={[{...unreachable, available: true}]}
        />,
      );

      expect(screen.queryByText('Unavailable')).toBeNull();
      expect(screen.getByRole('link', {name: 'Open'})).toBeInTheDocument();
    });

    it('summarizes an unreachable evidence section honestly', () => {
      render(<LearningView goal="goal" evidence={[unreachable]} />);

      expect(
        screen.getByText(
          'The full source could not be reached when this evidence was ' +
            'gathered, so it is listed without a summary.',
        ),
      ).toBeInTheDocument();
    });

    it('summarizes a retracted evidence section distinctly, not as unreachable', () => {
      render(
        <LearningView
          goal="goal"
          evidence={[{...unreachable, retracted: true}]}
        />,
      );

      expect(
        screen.getByText(
          'This source has been retracted, so it is listed without a summary.',
        ),
      ).toBeInTheDocument();
      expect(screen.queryByText(/could not be reached/)).toBeNull();
    });

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
});

describe('run detail retrieval degraded', () => {
  // The run-level retrieval notice on the Summary tab: a run that could
  // reach no literature source says so at the top of its report. Unlike a
  // degraded section, nothing else in the output hints at it -- the ideas,
  // reviews and tournament all look exactly like a healthy run's.

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

  it('names the run’s own documents when those were the floor', () => {
    renderWithReport({
      retrieval_degradation: {
        reason: 'mcp_unreachable',
        lost: ['literature_review'],
        floor: 'run_attachments',
      },
    });

    expect(
      screen.getByText(/Only the documents attached to this run/),
    ).toBeInTheDocument();
  });

  it('drops a capability name it has no words for', () => {
    // An engine that grows a new one should not print its identifier at a
    // reader; the sentence is still true without it.
    renderWithReport({
      retrieval_degradation: {
        reason: 'mcp_unreachable',
        lost: ['literature_review', 'some_future_thing'],
        floor: 'none',
      },
    });

    expect(screen.queryByText(/some_future_thing/)).not.toBeInTheDocument();
    expect(
      screen.getByText(/ran without the literature review/),
    ).toBeInTheDocument();
  });

  it('says nothing on a run that retrieved normally', () => {
    renderWithReport({});

    expect(
      screen.queryByText(/No literature source was reachable/),
    ).not.toBeInTheDocument();
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
    // The three fields must never be flattened back into an object repr.
    expect(document.body.textContent).not.toContain("{'focus_area'");
    expect(document.body.textContent).not.toContain('"focus_area"');
  });

  it('hides a section whose entries are all blank', () => {
    // The list length alone used to decide whether a heading rendered, so a list
    // of empty strings produced a heading with nothing beneath it.
    render(
      <AgentInsightsSection
        insights={makeInsights({contradictions: ['', '   ']})}
      />,
    );

    expect(
      screen.queryByRole('heading', {name: 'Contradictions'}),
    ).not.toBeInTheDocument();
    expect(screen.getByRole('heading', {name: 'Key findings'})).toBeVisible();
  });

  it('still renders a recommendation from an older persisted report', () => {
    // Report payloads are stored, so reports written before recommendations
    // kept their three fields hold one flattened string per entry.
    render(
      <AgentInsightsSection
        insights={makeInsights({
          recommended_directions: ['Measure binding directly by SPR.'],
        })}
      />,
    );

    expect(
      screen.getByText('Measure binding directly by SPR.'),
    ).toBeInTheDocument();
  });

  it('drops a recommendation with no focus area and no advice', () => {
    render(
      <AgentInsightsSection
        insights={makeInsights({
          recommended_directions: [
            {focus_area: '', recommendation: '', justification: 'Orphaned.'},
          ],
        })}
      />,
    );

    expect(
      screen.queryByRole('heading', {name: 'Recommended directions'}),
    ).not.toBeInTheDocument();
  });

  it('flags a meta-review that degraded to a fallback', () => {
    // L7: the meta-review-derived lists are blank after a fallback, so the
    // section must say generation failed instead of showing silence.
    render(<AgentInsightsSection insights={makeInsights()} degraded />);

    expect(
      screen.getByText(
        'This section could not be generated after repeated attempts.',
      ),
    ).toBeInTheDocument();
  });

  it('renders the degradation notice even without any insights payload', () => {
    render(<AgentInsightsSection insights={undefined} degraded />);

    expect(
      screen.getByRole('heading', {name: 'Agent Insights'}),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        'This section could not be generated after repeated attempts.',
      ),
    ).toBeInTheDocument();
  });

  it('shows no degradation notice for a clean run', () => {
    render(<AgentInsightsSection insights={makeInsights()} />);

    expect(
      screen.queryByText(
        'This section could not be generated after repeated attempts.',
      ),
    ).not.toBeInTheDocument();
  });

  it('renders saved insights with omitted lists', () => {
    render(<AgentInsightsSection insights={{key_findings: ['A finding.']}} />);
    expect(screen.getByText('A finding.')).toBeVisible();
    expect(screen.queryByText('Uncertainties')).not.toBeInTheDocument();
  });
});
