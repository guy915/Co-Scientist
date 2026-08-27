import {type IconName} from '@/components/icon';

// Each suggestion carries two strings with distinct jobs. `preview` is a
// one-sentence teaser shown on the card (truncated to the card width via
// TruncatedLabel) and in the hover bubble. `prompt` is the full, well-formed
// research goal dropped into the composer on click — modelled on the
// Co-Scientist input anatomy (a title line, a goal with an explicit output
// format, novelty/feasibility constraints, and the reasoning the system should
// perform), so a scientist starts from a real prompt rather than a teaser.
// `icon` is the leading glyph shown in the mobile list layout.
export const SUGGESTIONS: readonly {
  preview: string;
  prompt: string;
  icon: IconName;
}[] = [
  {
    preview: 'Repurpose an approved drug to slow glioblastoma progression.',
    prompt:
      'Repurposing an approved drug for glioblastoma.\n\n' +
      'Suggest an existing, approved drug that could be repurposed to slow ' +
      'the progression of glioblastoma, and provide experimentally ' +
      'testable concentrations for an in-vitro proliferation assay in ' +
      'patient-derived glioblastoma cells. The drug should cross the ' +
      'blood-brain barrier and inhibit tumor cell growth.\n\n' +
      'The drug should have minimal cytotoxicity in healthy neural and glial ' +
      'cells, and should not have been experimentally tested for ' +
      'glioblastoma before.\n\n' +
      'Reason about the drug’s molecular mechanism, impacted pathways, and ' +
      'effect on tumor-cell proliferation. Describe the mechanism of ' +
      'action in detail, and reason about safety and toxicity, stating ' +
      'where no safety data exists.',
    icon: 'search',
  },
  {
    preview:
      'Find a mechanistic link between gut-microbiome metabolites and ' +
      'Parkinson’s.',
    prompt:
      'A novel hypothesis for gut-microbiome metabolites in Parkinson’s ' +
      'disease progression.\n\n' +
      'Develop a novel, mechanistic hypothesis explaining how specific ' +
      'gut-microbiome-derived metabolites influence the progression of ' +
      'Parkinson’s disease, focusing on the gut–brain axis and α-synuclein ' +
      'aggregation. Explain the mechanism of action in detail, from the ' +
      'metabolite to the molecular pathway to the neuronal phenotype.\n\n' +
      'Prioritize hypotheses that are novel — not already established in the ' +
      'literature — and consistent with known human and model-organism ' +
      'evidence.\n\n' +
      'Include a feasible experiment to test the hypothesis, specifying the ' +
      'model system (for example gnotobiotic mice or enteric neuron ' +
      'cultures) and the measurable readout.',
    icon: 'lightbulb',
  },
  {
    preview:
      'Resensitize multidrug-resistant Gram-negative bacteria to an ' +
      'antibiotic.',
    prompt:
      'A strategy to resensitize multidrug-resistant Gram-negative ' +
      'bacteria.\n\n' +
      'Propose a novel strategy to resensitize multidrug-resistant ' +
      'Gram-negative bacteria (for example carbapenem-resistant Klebsiella ' +
      'pneumoniae) to an existing antibiotic. The strategy should target a ' +
      'specific resistance mechanism — such as an efflux pump, β-lactamase ' +
      'activity, or outer-membrane permeability — and restore the potency ' +
      'of a clinically used drug.\n\n' +
      'The approach should be feasible with current laboratory techniques ' +
      'and should not depend on developing an entirely new class of ' +
      'antibiotic.\n\n' +
      'Explain the molecular mechanism in detail, reason about how readily ' +
      'resistance could emerge against the strategy itself, and outline an ' +
      'experimentally testable assay (for example a checkerboard MIC ' +
      'assay) to validate the resensitization.',
    icon: 'stars',
  },
];

export type Suggestion = (typeof SUGGESTIONS)[number];

// Copy for the desktop-only 1-2-3 onboarding timeline rendered below the
// title (hidden on mobile to save vertical space; see the `!isMobile` guard).
export const SESSION_STEPS: readonly {
  n: number;
  title: string;
  body: string;
}[] = [
  {
    n: 1,
    title: 'Frame the research goal',
    body:
      'Describe the question, add useful context, and define what a ' +
      'strong hypothesis should satisfy.',
  },
  {
    n: 2,
    title: 'Generate hypotheses',
    body:
      'Co-Scientist explores mechanisms, evidence, and candidate ' +
      'explanations for the topic.',
  },
  {
    n: 3,
    title: 'Pressure-test the best ideas',
    body:
      'Hypotheses are compared against the criteria so the strongest ' +
      'directions rise to the top.',
  },
];
