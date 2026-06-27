import type {ReactNode} from 'react';
import {describe, it, expect, vi} from 'vitest';
import {render, screen} from '@testing-library/react';
import {IdeaModal} from './idea_modal';
import type {CitationRow, Evidence, Hypothesis, Review} from '@/api/runs';

// The Material web dialog relies on browser APIs jsdom lacks
// (IntersectionObserver, HTMLDialogElement.showModal, Element.animate), which
// surface as unhandled errors from its Lit lifecycle. Replace the thin
// MdDialog wrapper with a passthrough so IdeaModal's own rendering logic --
// lineage, reviews, and citation/evidence resolution -- is exercised in the
// light DOM without touching that lifecycle.
vi.mock('@/md3/md_dialog', () => ({
  MdDialog: ({
    headline,
    children,
    actions,
  }: {
    headline?: ReactNode;
    children: ReactNode;
    actions?: ReactNode;
  }) => (
    <div>
      {headline}
      {children}
      {actions}
    </div>
  ),
}));

function makeHypothesis(over: Partial<Hypothesis> = {}): Hypothesis {
  return {
    id: 'h1',
    run_id: 'r1',
    parent_id: null,
    generation: 0,
    title: 'Untitled hypothesis',
    statement: 'A statement.',
    mechanism: null,
    expected_effect: null,
    experimental_context: null,
    created_by_agent: 'generate',
    created_at: 0,
    elo_rating: 1200,
    win_count: 0,
    loss_count: 0,
    novelty_score: null,
    plausibility_score: null,
    testability_score: null,
    safety_status: null,
    status: null,
    cluster_id: null,
    ...over,
  };
}

describe('IdeaModal', () => {
  it('renders the hypothesis detail, lineage, reviews, and citations', () => {
    const child = makeHypothesis({
      id: 'h2',
      parent_id: 'h1',
      title: 'Evolved child idea',
      generation: 1,
    });
    const focus = makeHypothesis({
      id: 'h1',
      title: 'Parent idea: kinase inhibition',
      statement: 'Inhibiting the kinase reduces proliferation.',
      mechanism: 'Blocks ATP binding.',
      expected_effect: 'Reduced tumor growth.',
      elo_rating: 1275,
      win_count: 5,
      loss_count: 2,
    });
    const reviews: Review[] = [
      {
        id: 1,
        hypothesis_id: 'h1',
        reviewer_agent: 'reflection',
        summary: 'Mechanistically plausible.',
        critique: 'Lacks a dose-response rationale.',
        novelty: 8,
        plausibility: 7,
        testability: 6,
        overall: 7,
      },
    ];
    const evidence: Evidence[] = [
      {
        id: 'e1',
        title: 'Kinase inhibitor trial',
        source: 'PubMed',
        url: 'https://pubmed.example/e1',
        authors: ['Smith A'],
        year: 2022,
        abstract: '',
        available: true,
      },
    ];
    const citations: CitationRow[] = [
      {
        id: 1,
        hypothesis_id: 'h1',
        evidence_id: 'e1',
        claim: 'Inhibitor reduces proliferation.',
        state: 'verified',
      },
    ];

    render(
      <IdeaModal
        hypothesis={focus}
        allHypotheses={[focus, child]}
        reviews={reviews}
        citations={citations}
        evidence={evidence}
        onClose={() => {}}
      />,
    );

    // Headline + Elo badge.
    expect(
      screen.getByText('Parent idea: kinase inhibition'),
    ).toBeInTheDocument();
    expect(screen.getByText('Elo 1275')).toBeInTheDocument();

    // Body sections from the populated optional fields.
    expect(
      screen.getByText('Inhibiting the kinase reduces proliferation.'),
    ).toBeInTheDocument();
    expect(screen.getByText('Blocks ATP binding.')).toBeInTheDocument();
    expect(screen.getByText('Reduced tumor growth.')).toBeInTheDocument();

    // Lineage lists the evolved child.
    expect(screen.getByText('↓ Child: Evolved child idea')).toBeInTheDocument();

    // Review critique and citation claim are shown; citation resolves the
    // evidence title.
    expect(
      screen.getByText('Lacks a dose-response rationale.'),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Kinase inhibitor trial — Inhibitor reduces/),
    ).toBeInTheDocument();
  });

  it('renders deep-verification probes in a dedicated section', () => {
    const focus = makeHypothesis({id: 'h1', title: 'Verified idea'});
    const reviews: Review[] = [
      {
        id: 1,
        hypothesis_id: 'h1',
        reviewer_agent: 'reflection',
        summary: 'Plausible.',
        critique: 'Regular review critique.',
        novelty: null,
        plausibility: null,
        testability: null,
        overall: null,
      },
      {
        id: 2,
        hypothesis_id: 'h1',
        reviewer_agent: 'deep_verification',
        summary: 'Deep verification verdict: weakened',
        critique: 'Probe 1 (fundamental): Is X sufficient alone?',
        novelty: null,
        plausibility: null,
        testability: null,
        overall: null,
      },
    ];

    render(
      <IdeaModal
        hypothesis={focus}
        allHypotheses={[focus]}
        reviews={reviews}
        citations={[]}
        evidence={[]}
        onClose={() => {}}
      />,
    );

    // Dedicated section with the verdict parsed out of the summary into a badge.
    expect(screen.getByText('Deep verification')).toBeInTheDocument();
    expect(screen.getByText('weakened')).toBeInTheDocument();
    expect(
      screen.getByText(/Probe 1 \(fundamental\): Is X sufficient alone\?/),
    ).toBeInTheDocument();
    // The regular review still renders in its own section.
    expect(screen.getByText('Regular review critique.')).toBeInTheDocument();
  });

  it('calls onClose when the Close button is activated', () => {
    const onClose = vi.fn();
    render(
      <IdeaModal
        hypothesis={makeHypothesis({id: 'h1', title: 'Closable idea'})}
        allHypotheses={[]}
        reviews={[]}
        citations={[]}
        evidence={[]}
        onClose={onClose}
      />,
    );
    // The close action is an md-text-button with an inline onclick handler.
    const closeButton = screen.getByText('Close');
    closeButton.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
