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

/** Static metadata describing a public demonstration page. */
export interface PublicDemo {
  slug: string;
  title: string;
  researchGoal: string;
  summary: string;
  hypotheses: {
    title: string;
    statement: string;
  }[];
  evidenceSummary: string;
  relatedRunGoal: string;
  pageTitle: string;
  pageDescription: string;
  socialImage: string;
}

/** The curated list of public demonstrations shown in the marketing UI. */
export const publicDemos: PublicDemo[] = [
  {
    slug: 'ferroptosis-pancreatic-cancer',
    title: 'Ferroptosis in pancreatic cancer',
    researchGoal:
      'What are the key molecular regulators of ferroptosis in pancreatic cancer cells, and how might their modulation enhance chemotherapy sensitivity?',
    summary:
      'A completed demonstration exploring regulatory checkpoints that may connect ferroptosis sensitivity with chemotherapy response.',
    hypotheses: [
      {
        title: 'Regulatory feedback may define a ferroptosis-sensitive state',
        statement:
          'Coordinated perturbation of upstream redox regulation and lipid-peroxidation control may create a measurable window of chemotherapy sensitivity.',
      },
      {
        title: 'Metabolic bottlenecks may offer combination targets',
        statement:
          'Targeting a rate-limiting metabolic dependency alongside chemotherapy may produce a response distinct from either intervention alone.',
      },
      {
        title: 'Timing may matter as much as target selection',
        statement:
          'Sequencing ferroptosis modulation before chemotherapy may outperform simultaneous treatment by establishing a transient susceptible state.',
      },
    ],
    evidenceSummary:
      'The seeded demonstration reviews mock literature records and ranks ten generated hypotheses through deterministic pairwise debate. It is intended to demonstrate the workflow, not provide clinical guidance.',
    relatedRunGoal:
      'What are the key molecular regulators of ferroptosis in pancreatic cancer cells, and how might their modulation enhance chemotherapy sensitivity?',
    pageTitle: 'Ferroptosis in Pancreatic Cancer Demo - Co-Scientist',
    pageDescription:
      'Explore a completed Co-Scientist demonstration on ferroptosis regulation and chemotherapy sensitivity in pancreatic cancer.',
    socialImage: '/social-card.jpg',
  },
  {
    slug: 'synaptic-pruning-cognitive-flexibility',
    title: 'Synaptic pruning and cognitive flexibility',
    researchGoal:
      'How does synaptic pruning in the prefrontal cortex contribute to cognitive flexibility during adolescent development?',
    summary:
      'A completed demonstration examining how developmental timing, circuit refinement, and regulatory feedback could influence cognitive flexibility.',
    hypotheses: [
      {
        title: 'Pruning may improve signal separation',
        statement:
          'Selective removal of weak prefrontal connections may increase the separability of competing task representations during adolescence.',
      },
      {
        title: 'A transient plasticity window may coordinate refinement',
        statement:
          'Temporally restricted pruning may preserve exploratory flexibility before stabilizing mature circuit configurations.',
      },
      {
        title: 'Local inhibitory control may gate pruning outcomes',
        statement:
          'Changes in inhibitory tone may determine whether pruning produces adaptive flexibility or overly rigid task representations.',
      },
    ],
    evidenceSummary:
      'The seeded demonstration uses deterministic mock evidence and a full generate, reflect, rank, evolve, and synthesize workflow. Its outputs are illustrative research hypotheses.',
    relatedRunGoal:
      'How does synaptic pruning in the prefrontal cortex contribute to cognitive flexibility during adolescent development?',
    pageTitle: 'Synaptic Pruning and Cognitive Flexibility Demo - Co-Scientist',
    pageDescription:
      'Explore a completed Co-Scientist demonstration on adolescent synaptic pruning and cognitive flexibility.',
    socialImage: '/social-card.jpg',
  },
  {
    slug: 'biofilm-antibiotic-resistance',
    title: 'Biofilm antibiotic resistance',
    researchGoal:
      'What mechanisms drive antibiotic resistance in Staphylococcus aureus biofilms, and which metabolic pathways could be targeted to restore susceptibility?',
    summary:
      'A completed demonstration investigating metabolic and regulatory mechanisms that may sustain antibiotic tolerance in biofilms.',
    hypotheses: [
      {
        title: 'Metabolic state may sustain tolerant subpopulations',
        statement:
          'A constrained metabolic program may preserve a slow-growing subpopulation that survives antibiotic exposure within the biofilm.',
      },
      {
        title: 'Redox control may be a sensitization point',
        statement:
          'Perturbing redox homeostasis may weaken the biofilm stress response and restore susceptibility to conventional antibiotics.',
      },
      {
        title: 'Sequential treatment may disrupt recovery',
        statement:
          'A metabolic priming step followed by antibiotic treatment may prevent tolerant cells from returning to active growth.',
      },
    ],
    evidenceSummary:
      'The seeded demonstration ranks ten mock-generated hypotheses against deterministic evidence and review signals. It is a product example rather than a validated treatment recommendation.',
    relatedRunGoal:
      'What mechanisms drive antibiotic resistance in Staphylococcus aureus biofilms, and which metabolic pathways could be targeted to restore susceptibility?',
    pageTitle: 'Biofilm Antibiotic Resistance Demo - Co-Scientist',
    pageDescription:
      'Explore a completed Co-Scientist demonstration on metabolic pathways and antibiotic resistance in Staphylococcus aureus biofilms.',
    socialImage: '/social-card.jpg',
  },
];

/** The demo highlighted as the primary featured example. */
export const featuredDemo = publicDemos[0];

/**
 * Looks up a public demo by its slug.
 *
 * @param slug The demo slug, or undefined.
 * @returns The matching demo, or undefined if none matches.
 */
export function getPublicDemo(
  slug: string | undefined,
): PublicDemo | undefined {
  return publicDemos.find(demo => demo.slug === slug);
}
