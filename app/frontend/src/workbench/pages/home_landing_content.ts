import type {IconName} from '@/components/icon';
import type {ShapeName} from './home_landing_hooks';

// Static copy and product facts for the landing page under the chat home
// (see home_landing.tsx). Every number here is the product's own: the tier
// table mirrors RUN_TIER_DEFAULTS in app/app/run_modes/, and the starting
// Elo mirrors INITIAL_ELO_RATING in the engine's constants/tournament.py.
// Keep them in step when either source changes.

/** Tonal container families the landing page paints its shapes with. */
export type LandingTone = 'teal' | 'blue' | 'green' | 'yellow' | 'red';

/** The rating every idea enters the tournament with. */
export const INITIAL_ELO = 1200;

/** One section of the landing page, as the sticky tab rail lists it. */
export interface LandingSection {
  id: string;
  label: string;
}

// In page order. The ids double as the DOM ids the rail scrolls to.
export const LANDING_SECTIONS: readonly LandingSection[] = [
  {id: 'landing-overview', label: 'Overview'},
  {id: 'landing-how', label: 'How it works'},
  {id: 'landing-tournament', label: 'Tournament'},
  {id: 'landing-evidence', label: 'Evidence'},
  {id: 'landing-safety', label: 'Safety'},
  {id: 'landing-tiers', label: 'Tiers'},
  {id: 'faq', label: 'FAQ'},
];

/** A specialist agent, as its card and the system diagram present it. */
export interface LandingAgent {
  name: string;
  summary: string;
  icon: IconName;
  shape: ShapeName;
  tone: LandingTone;
}

// Supervisor first: its card spans the grid, the six specialists follow in
// the order the paper introduces them.
export const LANDING_AGENTS: readonly LandingAgent[] = [
  {
    name: 'Supervisor',
    summary:
      'Reads your goal, writes the research plan, and decides which agent ' +
      'works next based on how the pool is changing.',
    icon: 'account_tree',
    shape: 'cookie12',
    tone: 'teal',
  },
  {
    name: 'Generation',
    summary:
      'Drafts new hypotheses from the literature and simulated scientific ' +
      'debate.',
    icon: 'lightbulb',
    shape: 'flower',
    tone: 'blue',
  },
  {
    name: 'Reflection',
    summary: 'Reviews each idea for correctness, novelty, and testability.',
    icon: 'rate_review',
    shape: 'gem',
    tone: 'red',
  },
  {
    name: 'Ranking',
    summary: 'Runs the Elo tournament of head-to-head debates.',
    icon: 'leaderboard',
    shape: 'pill',
    tone: 'yellow',
  },
  {
    name: 'Evolution',
    summary: 'Breeds improved children from the strongest ideas.',
    icon: 'genetics',
    shape: 'clover',
    tone: 'green',
  },
  {
    name: 'Proximity',
    summary: 'Clusters near-duplicates so matches test real differences.',
    icon: 'join',
    shape: 'cookie7',
    tone: 'blue',
  },
  {
    name: 'Meta-review',
    summary: 'Learns from every debate and writes the research overview.',
    icon: 'summarize',
    shape: 'sunny',
    tone: 'teal',
  },
];

/** One of the three safety layers. */
export interface LandingSafetyLayer {
  title: string;
  body: string;
  icon: IconName;
  shape: ShapeName;
  tone: LandingTone;
}

export const LANDING_SAFETY: readonly LandingSafetyLayer[] = [
  {
    title: 'Goal screening',
    body: 'Every research goal is checked at intake, before any agent starts work.',
    icon: 'policy',
    shape: 'clover',
    tone: 'yellow',
  },
  {
    title: 'Idea screening',
    body: 'Each hypothesis is screened again before it can enter the tournament.',
    icon: 'verified_user',
    shape: 'sunny',
    tone: 'red',
  },
  {
    title: 'Human review',
    body: 'Anything held waits for a person to decide. Nothing held is published on its own.',
    icon: 'person',
    shape: 'cookie7',
    tone: 'blue',
  },
];

/** A run tier's pool size, from RUN_TIER_DEFAULTS. */
export interface LandingTier {
  name: string;
  seeds: number;
  cycles: number;
  maxIdeas: number;
}

export const LANDING_TIERS: readonly LandingTier[] = [
  {name: 'Express', seeds: 4, cycles: 1, maxIdeas: 12},
  {name: 'Standard', seeds: 8, cycles: 2, maxIdeas: 32},
  {name: 'Extended', seeds: 12, cycles: 3, maxIdeas: 60},
  {name: 'Ultra', seeds: 16, cycles: 4, maxIdeas: 96},
];

/** The tier a run starts on unless the researcher picks another. */
export const DEFAULT_TIER = 'Standard';

/** The largest pool any tier can grow, i.e. the tier grid's dot count. */
export const MAX_POOL = 96;

// The literature and data tools the agents read, for the sources marquee.
export const LANDING_SOURCES: readonly string[] = [
  'PubMed',
  'Europe PMC',
  'OpenAlex',
  'ChEMBL',
  'UniProt',
  'INDRA',
  'bioRxiv',
  'medRxiv',
  'The open web',
];

/** One claim-check verdict, as the Evidence section explains it. */
export interface LandingVerdict {
  label: string;
  body: string;
  tone: LandingTone;
}

export const LANDING_VERDICTS: readonly LandingVerdict[] = [
  {
    label: 'Supports',
    body: 'A passage states the claim or its direct mechanism.',
    tone: 'green',
  },
  {
    label: 'Partial',
    body: 'A passage supports part of the claim, or under narrower conditions.',
    tone: 'yellow',
  },
  {
    label: 'Contradicts',
    body: 'A passage on the same subject states the opposite.',
    tone: 'red',
  },
];

/** One question in the landing page's FAQ. */
export interface FaqEntry {
  question: string;
  answer: string;
}

// The product FAQ. It used to live in Settings > Help; that section now
// links here instead, so this is the one copy.
export const FAQ: readonly FaqEntry[] = [
  {
    question: 'What is Co-Scientist?',
    answer:
      'A multi-agent workspace that generates, debates, and ranks research ' +
      'hypotheses for a goal you set. A team of agents proposes ideas, ' +
      'reviews them, and runs a tournament so the strongest directions rise ' +
      'to the top.',
  },
  {
    question: 'How do I start a run?',
    answer:
      'From the home screen, describe your research goal in the composer and ' +
      'send it. Co-Scientist confirms the setup, then the agents generate ' +
      'and evaluate ideas. Follow progress and results in the run view.',
  },
  {
    question: 'What does a run produce?',
    answer:
      'A ranked set of hypotheses, each with reviews, an Elo rating from the ' +
      'tournament, and claims checked against the literature. It also writes ' +
      'a research overview with open questions and draft specific aims.',
  },
  {
    question: 'Where does the evidence come from?',
    answer:
      'From literature tools such as PubMed, Europe PMC, preprint servers, ' +
      'OpenAlex, ChEMBL, UniProt, and INDRA, plus the web when search is on. ' +
      'Turn sources on or off from Connectors in the composer.',
  },
  {
    question: 'Are the results true?',
    answer:
      'They are hypotheses, not findings. Co-Scientist ranks ideas by ' +
      'argument and evidence so you can decide which ones deserve an ' +
      'experiment.',
  },
  {
    question: 'Do I need an API key?',
    answer:
      'No. Without a key you are on free usage: you can start Express runs ' +
      'only, up to 3 per day on this device. Add your own key under Model ' +
      'to use every run type without a daily limit.',
  },
  {
    question: 'Which model does it use?',
    answer:
      'Without an API key, runs use the free model configured for the ' +
      'deployment. When you add your own API key under Model, you choose a ' +
      'supervisor model (planning and the final report) and a worker model ' +
      '(generating, reviewing, and ranking ideas) from your provider.',
  },
  {
    question: 'Where does my API key go?',
    answer:
      'The key you enter under Model is stored in this browser and sent to ' +
      'the server when you start a run or chat with the Agent. The server ' +
      'checks it with the provider, then stores it encrypted for that run ' +
      'only and never returns it. Clearing your browser storage removes the ' +
      'local copy.',
  },
];

// Elo helpers behind the landing page's tournament visuals. The chart and
// the tree are illustrations, labeled as such on the page, but the rating
// update itself is the real Elo rule, starting every idea at INITIAL_ELO.

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
