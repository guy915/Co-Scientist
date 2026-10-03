import {afterEach, describe, expect, it} from 'vitest';
import type {Interview} from '@/api/runs';
import {setStoredApiKey} from '@/lib/client_id';
import {
  applyEditedInterviewFields,
  availableTierOptions,
  buildInterviewFieldsPayload,
  isCompletionEmailValid,
  isValidCompletionEmail,
  interviewToRunSpec,
} from './run_spec';
import {makeSpec} from '@/test_fixtures';

afterEach(() => setStoredApiKey(''));

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
      tier: 'express',
      notifyOnCompletion: false,
      completionEmail: '',
    });
  });

  it('defaults to Standard once an API key is stored', () => {
    setStoredApiKey('sk-test');
    expect(interviewToRunSpec({fields: {}} as Interview).tier).toBe('standard');
  });
});

describe('availableTierOptions', () => {
  it('leaves only Express open to free usage', () => {
    const open = availableTierOptions().filter(option => !option.disabled);
    expect(open.map(option => option.id)).toEqual(['express']);
  });

  it('opens every run type with an API key', () => {
    setStoredApiKey('sk-test');
    expect(availableTierOptions().some(option => option.disabled)).toBe(false);
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

describe('isValidCompletionEmail', () => {
  it('accepts anything@anything.tld', () => {
    expect(isValidCompletionEmail('scientist@example.com')).toBe(true);
  });

  it('rejects text with no @ or no domain dot', () => {
    expect(isValidCompletionEmail('not-an-address')).toBe(false);
    expect(isValidCompletionEmail('')).toBe(false);
  });
});

describe('isCompletionEmailValid', () => {
  it('never blocks starting a run when notification is off, valid or not', () => {
    expect(
      isCompletionEmailValid(
        makeSpec({notifyOnCompletion: false, completionEmail: 'garbage'}),
      ),
    ).toBe(true);
  });

  it('passes once notification is on with a valid address', () => {
    expect(
      isCompletionEmailValid(
        makeSpec({
          notifyOnCompletion: true,
          completionEmail: 'scientist@example.com',
        }),
      ),
    ).toBe(true);
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
