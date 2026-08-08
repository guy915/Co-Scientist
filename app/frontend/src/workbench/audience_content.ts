import {type Audience} from './audience_context';

// DRAFT copy for the audience modes. Edit freely — no logic depends on the
// wording, only on the exported shapes.

export const AUDIENCE_OPTIONS: {
  value: Audience;
  title: string;
  blurb: string;
}[] = [
  {
    value: 'google',
    title: 'Google AI Co-Scientist team',
    blurb: 'A note from the author and recommendations for the product.',
  },
  {
    value: 'sbi_ucd',
    title: 'SBI / UCD researcher',
    blurb: 'Early-access mode tailored to your lab and research.',
  },
  {
    value: 'general',
    title: 'General',
    blurb: 'The standard Co-Scientist workspace.',
  },
];

// The Google team's header control: a link straight to the proposals graph,
// which is what the note it replaced existed to point at. Named in English
// like every other control in this header -- it briefly inherited the
// Hebrew wording of the note's own link, which left one right-to-left pill
// in a left-to-right header.
export const GOOGLE_PROPOSALS: {label: string; to: string} = {
  label: 'Proposals',
  to: '/proposals',
};

// DRAFT: copy for the SBI/UCD feedback form in the header popover.
export const PILOT_FEEDBACK: {
  title: string;
  intro: string;
  // What happens to a submitted note: who can see it and how long it is
  // kept. Rendered under `intro`, in its own line so it stays skimmable
  // rather than folded into the invitation-to-write copy above it.
  privacyNote: string;
  placeholder: string;
  submit: string;
  sending: string;
  thanks: string;
  error: string;
} = {
  title: 'Send feedback',
  intro:
    'You are an early tester. Tell us what broke, what confused you, or ' +
    'what you wish it did.',
  privacyNote:
    'Notes are stored against your browser identity and reviewed by the ' +
    'team; they are kept for a limited time, not shared beyond the team, ' +
    'and never shown back in the workspace.',
  placeholder: 'What would you like us to know?',
  submit: 'Send',
  sending: 'Sending...',
  thanks: 'Thanks — your feedback was sent.',
  error: 'Could not send that. Please try again.',
};

// Category options offered by the feedback form. The values mirror
// FEEDBACK_CATEGORIES in app/feedback.py, which validates them.
export const FEEDBACK_CATEGORIES: readonly {
  value: 'bug' | 'suggestion' | 'question' | 'praise';
  label: string;
}[] = [
  {value: 'bug', label: 'Bug'},
  {value: 'suggestion', label: 'Suggestion'},
  {value: 'question', label: 'Question'},
  {value: 'praise', label: 'Praise'},
];

// DRAFT: SBI/UCD-tailored home suggestions. Same shape as the default
// SUGGESTIONS in pages/chat_home_suggestions.ts.
export const SBI_SUGGESTIONS: readonly {
  preview: string;
  prompt: string;
  icon: 'search' | 'lightbulb' | 'stars';
}[] = [
  {
    preview: 'Propose a resistance mechanism to a MAPK-pathway inhibitor.',
    prompt:
      'A novel resistance mechanism to MAPK-pathway inhibition in cancer.\n\n' +
      'Develop a mechanistic hypothesis for how tumor cells acquire ' +
      'resistance to a MEK or ERK inhibitor through signalling-network ' +
      'rewiring. Explain the pathway-level mechanism and a ' +
      'phospho-signalling ' +
      'readout that would detect it.\n\n' +
      'Prioritize hypotheses testable with proteomic and perturbation ' +
      'assays common to a systems-biology lab.',
    icon: 'lightbulb',
  },
  {
    preview: 'Find a synthetic-lethal partner for a common oncogenic driver.',
    prompt:
      'A synthetic-lethal vulnerability for an oncogenic driver.\n\n' +
      'Identify a candidate synthetic-lethal gene or pathway for a common ' +
      'oncogenic driver (for example KRAS or PIK3CA), grounded in ' +
      'signalling-network biology. Describe the mechanism and a CRISPR or ' +
      'small-molecule perturbation screen to validate it.',
    icon: 'search',
  },
  {
    preview: 'Explain cell-to-cell signalling heterogeneity in a tumor.',
    prompt:
      'A mechanistic hypothesis for signalling heterogeneity in tumors.\n\n' +
      'Propose why genetically similar tumor cells show heterogeneous ' +
      'signalling-pathway activity, focusing on network-level feedback. ' +
      'Specify a single-cell measurement that would test the hypothesis.',
    icon: 'stars',
  },
];
