// Real hypotheses from the production demo run 285b7684 ("Metabolic
// Vulnerabilities in S. aureus Biofilms"), via GET /api/runs/{id}/hypotheses:
// nine generation-0 seeds plus six "Refined:" children = 15 ideas, 21 matches.
export const SEEDS = [
  {title: 'Metabolic wake-up before vancomycin exposure', elo: 1386},
  {title: 'MazEF state predicts a tolerant biofilm subpopulation', elo: 1371},
  {title: 'Matrix-restricted nutrient access creates a reversible tolerance niche', elo: 1356},
  {title: 'Oxygen-gradient collapse reveals an antibiotic-sensitive sublayer', elo: 1341},
  {title: 'MazEF–ica epistasis partitions biomass from tolerance', elo: 1326},
  {title: 'Persister exit kinetics nominate a sequential killing window', elo: 1311},
  {title: 'Small-colony variants are a reversible lineage state, not an endpoint', elo: 1296},
  {title: 'Respiratory stimulation has a narrow therapeutic index in established biofilms', elo: 1281},
  {title: 'Matrix permeability and cell state make independent contributions to tolerance', elo: 1266},
];

/** Each refined child's parent, as an index into SEEDS. */
export const REFINED_PARENTS = [0, 1, 2, 3, 4, 5];

export const IDEA_COUNT = SEEDS.length + REFINED_PARENTS.length;
export const MATCH_COUNT = 21;
