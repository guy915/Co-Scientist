import {describe, expect, it} from 'vitest';
import type {Interview} from '@/api/runs';
import {
  applyEditedInterviewFields,
  buildInterviewFieldsPayload,
  interviewToRunSpec,
} from './run_spec';

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
      notifyOnCompletion: false,
      completionEmail: '',
    });
  });
});

describe('buildInterviewFieldsPayload', () => {
  it('maps the editor form values onto the PUT /fields request shape', () => {
    expect(
      buildInterviewFieldsPayload({
        goal: 'Explain treatment resistance.',
        title: 'Resistance mechanisms',
        attributes: ['Tumor metabolism'],
        requirements: ['Prioritize human evidence'],
      }),
    ).toEqual({
      research_challenge: 'Explain treatment resistance.',
      focus_area: ['Tumor metabolism'],
      preferences: ['Prioritize human evidence'],
      title: 'Resistance mechanisms',
    });
  });

  it('sends a blank title as null, matching the unedited card', () => {
    expect(
      buildInterviewFieldsPayload({
        goal: 'Explain treatment resistance.',
        title: '   ',
        attributes: [],
        requirements: [],
      }).title,
    ).toBeNull();
  });
});

describe('applyEditedInterviewFields', () => {
  it('maps a PUT /fields response back onto the run-spec field names', () => {
    const interview = {
      id: 'interview-2',
      fields: {
        research_challenge: 'Revised challenge.',
        focus_area: ['A'],
        preferences: ['B'],
        title: null,
      },
    } as Interview;

    expect(applyEditedInterviewFields(interview)).toEqual({
      interviewId: 'interview-2',
      title: null,
      goal: 'Revised challenge.',
      attributes: ['A'],
      requirements: ['B'],
    });
  });
});
