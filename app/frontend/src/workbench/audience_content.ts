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

// The address the contact button writes to, and the compose window it opens.
// A Gmail compose link rather than a `mailto:`: the reviewers write from
// their Google accounts, so composing in Gmail puts the right sender on the
// message and opens in a tab, which `mailto:` cannot do.
const CONTACT_ADDRESS = 'guybarel2006@gmail.com';
const CONTACT_SUBJECT = 'AI Co-Scientist';

function composeUrl(to: string, subject: string): string {
  const query = new URLSearchParams({
    view: 'cm',
    fs: '1',
    to,
    su: subject,
  });
  return `https://mail.google.com/mail/?${query}`;
}

// DRAFT: personal note shown to the Google team in the header popover. The
// reviewing team is Israeli, so the note itself is in Hebrew and renders RTL
// (see GoogleTeamControl, which sets dir/lang). The header button that opens
// it stays in English, as does the affiliation chooser: both are read before
// anyone has been addressed as part of the team.
export const GOOGLE_NOTE: {
  label: string;
  message: string;
  linkLabel: string;
  aboutLabel: string;
  aboutUrl: string;
  contactLabel: string;
  contactUrl: string;
} = {
  label: 'Message to the team',
  // English source, kept alongside the translation so the wording can be
  // revised without back-translating: "This is an independent recreation of
  // AI Co-Scientist, built to learn how the system works. After reading the
  // paper and researching competitors, I've added a few suggestions for the
  // official product."
  message:
    'זה שחזור עצמאי של AI Co-Scientist, שנבנה כדי ללמוד איך המערכת עובדת. ' +
    'לאחר שקראתי את המאמר וחקרתי על מתחרים, הוספתי כמה הצעות למוצר הרשמי.',
  linkLabel: 'לצפייה בהצעות',
  aboutLabel: 'קצת עליי',
  aboutUrl: 'https://guybarel.me/',
  contactLabel: 'צרו קשר',
  contactUrl: composeUrl(CONTACT_ADDRESS, CONTACT_SUBJECT),
};

// DRAFT: copy for the SBI/UCD feedback form in the header popover.
export const PILOT_FEEDBACK: {
  title: string;
  intro: string;
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
// SUGGESTIONS in chat_home_stage.tsx.
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
