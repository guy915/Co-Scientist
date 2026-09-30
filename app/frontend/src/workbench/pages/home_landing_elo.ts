// Elo simulations behind the landing page's tournament visuals. Both are
// illustrations, labeled as such on the page, but the rating update itself is
// the real Elo rule, starting every idea at the product's INITIAL_ELO.

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

/** One idea in the live arena: a position, a velocity, and a rating. */
export interface ArenaIdea {
  x: number;
  y: number;
  vx: number;
  vy: number;
  elo: number;
  quality: number;
  phase: number;
}

/** A just-played match, drawn as a fading link and a burst on the winner. */
export interface ArenaSpark {
  a: ArenaIdea;
  b: ArenaIdea;
  winner: ArenaIdea;
  age: number;
}

const ARENA_K = 24;

/** Seeds `count` ideas scattered across a `width` x `height` field. */
export function seedArena(
  count: number,
  width: number,
  height: number,
): ArenaIdea[] {
  return Array.from({length: count}, () => ({
    x: Math.random() * width,
    y: Math.random() * height,
    vx: 0,
    vy: 0,
    elo: INITIAL_ELO,
    quality: Math.random(),
    phase: Math.random() * Math.PI * 2,
  }));
}

// Picks a nearby opponent for `a`: the closest of a few random draws, so
// matches read as local skirmishes rather than lines across the field.
function nearbyOpponent(ideas: ArenaIdea[], a: ArenaIdea): ArenaIdea | null {
  let best: ArenaIdea | null = null;
  let bestDistance = Infinity;
  for (let k = 0; k < 8; k++) {
    const c = ideas[Math.floor(Math.random() * ideas.length)];
    const d = Math.hypot(c.x - a.x, c.y - a.y);
    if (c !== a && d < bestDistance) {
      best = c;
      bestDistance = d;
    }
  }
  return best;
}

/**
 * Plays one match between a random idea and a neighbor. The outcome leans
 * on each idea's hidden quality as well as the Elo expectation, so better
 * ideas rise over time. Returns the spark to draw, or null if no match ran.
 */
export function playArenaMatch(ideas: ArenaIdea[]): ArenaSpark | null {
  const a = ideas[Math.floor(Math.random() * ideas.length)];
  const b = nearbyOpponent(ideas, a);
  if (!b) return null;
  const expected = expectedScore(a.elo, b.elo);
  const odds = expected * 0.5 + (a.quality - b.quality) * 0.5 + 0.25;
  const aWins = Math.random() < odds ? 1 : 0;
  const delta = ARENA_K * (aWins - expected);
  a.elo += delta;
  b.elo -= delta;
  return {a, b, winner: aWins ? a : b, age: 0};
}
