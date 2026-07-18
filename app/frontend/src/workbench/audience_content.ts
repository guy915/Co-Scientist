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

// DRAFT: personal message shown to the Google team in the header popover.
export const GOOGLE_MESSAGE =
  'Thank you for the AI Co-Scientist work that inspired this project. ' +
  'This is an independent replication built to study the architecture. ' +
  'I would love your feedback — see my recommendations for the product.';

// DRAFT: recommendations page copy (heading + bullet points).
export const GOOGLE_RECOMMENDATIONS: {heading: string; points: string[]} = {
  heading: 'Recommendations for the official Co-Scientist',
  points: [
    'Surface the tournament reasoning to end users, not just final ranks.',
    'Make literature-grounding failures visible instead of silent.',
    'Offer a lightweight express tier for fast iteration.',
  ],
};

// DRAFT: SBI/UCD early-access pilot guide shown in the header popover.
export const PILOT_GUIDE: {
  title: string;
  intro: string;
  tryThese: string[];
  limitations: string[];
} = {
  title: 'Early access',
  intro:
    'Welcome to the SBI/UCD pilot. Co-Scientist is tailored to your ' +
    'signalling and cancer-biology work.',
  tryThese: [
    'Ask for mechanistic hypotheses grounded in signalling networks.',
    'Request an experiment plan for a promising hypothesis.',
  ],
  limitations: [
    'Literature grounding is best-effort and may miss recent work.',
    'Runs can take several minutes at higher tiers.',
  ],
};

// DRAFT: feedback address for the pilot.
export const PILOT_FEEDBACK_EMAIL = 'guybarel2006@gmail.com';

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
      'rewiring. Explain the pathway-level mechanism and a phospho-signalling ' +
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
