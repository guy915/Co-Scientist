import {describe, expect, it} from 'vitest';
import type {Interview} from '@/api/runs';
import {interviewToRunSpec} from './run_spec';

describe('interviewToRunSpec', () => {
  it('maps only the durable Agent derivation into run configuration', () => {
    const interview = {
      id: 'interview-1',
      fields: {
        research_challenge: 'Explain treatment resistance.',
        focus_area: ['Tumor metabolism', 'Causal mechanisms'],
        preferences: ['Prioritize human evidence'],
        title: 'Resistance mechanisms',
      },
    } as Interview;

    expect(interviewToRunSpec(interview)).toEqual({
      interviewId: 'interview-1',
      title: 'Resistance mechanisms',
      goal: 'Explain treatment resistance.',
      requirements: ['Prioritize human evidence'],
      attributes: ['Tumor metabolism', 'Causal mechanisms'],
      criteria: [],
      focus: 'balance',
      tier: 'standard',
    });
  });
});
