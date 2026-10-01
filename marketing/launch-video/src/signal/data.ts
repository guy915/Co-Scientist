import {MATCH_COUNT, REFINED_PARENTS, SEEDS} from '../data/demo_run';

// The leaderboard shows the run's top five.
export const BOARD = SEEDS.slice(0, 5);

export const FINAL_ELO = SEEDS.map(s => s.elo);
export const SEED_COUNT = SEEDS.length;

const lcg = (seed: number) => () => ((seed = (seed * 1664525 + 1013904223) >>> 0) / 2 ** 32);

/** Seeded pairings, one per match the demo run played. */
export const MATCHES: [number, number][] = (() => {
  const r = lcg(11);
  const out: [number, number][] = [];
  while (out.length < MATCH_COUNT) {
    const a = Math.floor(r() * SEED_COUNT);
    const b = Math.floor(r() * SEED_COUNT);
    if (a !== b) out.push([a, b]);
  }
  return out;
})();

/** One refined child per parent, as in the run. */
export const CHILDREN = REFINED_PARENTS.map(parent => ({parent}));

// Sources are real tools the reference MCP server exposes.
export const SOURCES = ['PUBMED', 'UNIPROT', 'REACTOME', 'CLINICALTRIALS.GOV', 'OPEN TARGETS', 'CHEMBL'];
