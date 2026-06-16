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

import {describe, it, expect} from 'vitest';
import {render, screen} from '@testing-library/react';
import {OverviewTab} from './OverviewTab';
import type {SafetyDecision} from '@/api/runs';
import type {StreamEvent} from '@/hooks/useRunStream';

describe('OverviewTab', () => {
  it('shows the waiting empty state when there are no events', () => {
    render(
      <OverviewTab
        run={null}
        hypotheses={[]}
        evidence={[]}
        matches={[]}
        safety={[]}
        events={[]}
      />,
    );
    expect(screen.getByText('Waiting for events…')).toBeInTheDocument();
    // Stat blocks (rendered twice for responsive layouts) still appear.
    expect(screen.getAllByText('Hypotheses').length).toBeGreaterThanOrEqual(1);
  });

  it('renders the pipeline timeline with humanized agent labels', () => {
    const events: StreamEvent[] = [
      {seq: 1, type: 'generate', payload: {hypotheses: [{}, {}, {}]}},
      {
        seq: 2,
        type: 'ranking',
        payload: {iteration: 1, matches: [{}, {}]},
      },
    ];
    render(
      <OverviewTab
        run={null}
        hypotheses={[]}
        evidence={[]}
        matches={[]}
        safety={[]}
        events={events}
      />,
    );
    expect(screen.getByText('Generation')).toBeInTheDocument();
    expect(screen.getByText('3 initial hypotheses')).toBeInTheDocument();
    expect(screen.getByText('Ranking')).toBeInTheDocument();
    expect(screen.getByText('iter 1 · 2 matches')).toBeInTheDocument();
  });

  it('renders the safety section when a decision blocks output', () => {
    const safety: SafetyDecision[] = [
      {
        stage: 'intake',
        decision: 'block',
        reason: 'Requests a controlled pathogen enhancement.',
        matches: ['bio.weapon'],
        created_at: 1700000000,
      },
    ];
    render(
      <OverviewTab
        run={null}
        hypotheses={[]}
        evidence={[]}
        matches={[]}
        safety={safety}
        events={[]}
      />,
    );
    expect(screen.getByText('Safety decisions')).toBeInTheDocument();
    expect(
      screen.getByText('Requests a controlled pathogen enhancement.'),
    ).toBeInTheDocument();
  });
});
