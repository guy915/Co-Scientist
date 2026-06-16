/**
 * Copyright 2026 The Co-Scientist Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import type {ReactNode} from 'react';
import {describe, it, expect, vi} from 'vitest';
import {render, screen} from '@testing-library/react';
import {IdeaModal} from './IdeaModal';
import type {CitationRow, Evidence, Hypothesis, Review} from '@/api/runs';

// The Material web dialog relies on browser APIs jsdom lacks
// (IntersectionObserver, HTMLDialogElement.showModal, Element.animate), which
// surface as unhandled errors from its Lit lifecycle. Replace the thin
// MdDialog wrapper with a passthrough so IdeaModal's own rendering logic --
// lineage, reviews, and citation/evidence resolution -- is exercised in the
// light DOM without touching that lifecycle.
vi.mock('@/md3/MdDialog', () => ({
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
