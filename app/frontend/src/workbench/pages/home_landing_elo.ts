// Elo helpers behind the landing page's tournament visuals. The chart and
// the tree are illustrations, labeled as such on the page, but the rating
// update itself is the real Elo rule, starting every idea at INITIAL_ELO.

import {INITIAL_ELO} from './home_landing_content';

/** Expected score of a player rated `a` against one rated `b`. */
export function expectedScore(a: number, b: number): number {
  return 1 / (1 + 10 ** ((b - a) / 400));
}

// Park-Miller generator, so the chart is identical on every load.
function seededRandom(seed: number): () => number {
  let state = seed;
  return () => {
    state = (state * 16807) % 2147483647;
    return state / 2147483647;
  };
}

/** The rating history of a seeded tournament, one snapshot per match. */
export interface EloHistory {
  /** history[m][i]: idea i's rating after m matches (m = 0 is the start). */
  history: number[][];
  /** Index of the idea that finished highest. */
  leader: number;
}

const CHART_K = 32;

// Plays one seeded match between two random ideas and updates both ratings.
function playChartMatch(
  elo: number[],
  skill: readonly number[],
  random: () => number,
) {
  const a = Math.floor(random() * elo.length);
  let b = Math.floor(random() * (elo.length - 1));
  if (b >= a) b++;
  const expected = expectedScore(elo[a], elo[b]);
  const aWins = random() < skill[a] / (skill[a] + skill[b]) ? 1 : 0;
  elo[a] += CHART_K * (aWins - expected);
  elo[b] -= CHART_K * (aWins - expected);
}

/**
 * Plays a seeded tournament of `ideas` ideas over `matches` matches. Idea 0
 * is given the strongest underlying quality so the chart tells a story, but
 * it still has to win its matches for its rating to climb.
 */
export function simulateEloHistory(
  ideas = 8,
  matches = 64,
  seed = 7,
): EloHistory {
  const random = seededRandom(seed);
  const skill = Array.from({length: ideas}, (_, i) =>
    i === 0 ? 0.92 : 0.3 + random() * 0.28,
  );
  const elo = Array<number>(ideas).fill(INITIAL_ELO);
  const history = [elo.slice()];
  for (let m = 0; m < matches; m++) {
    playChartMatch(elo, skill, random);
    history.push(elo.slice());
  }
  return {history, leader: elo.indexOf(Math.max(...elo))};
}
