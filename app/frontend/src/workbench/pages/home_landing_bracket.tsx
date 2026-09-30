// The Tournament section's tree: eight example ideas debate in pairs, round
// by round, and each result moves both ratings by the real Elo rule. The
// tree plays itself round by round while it is on screen, then starts over;
// under reduced motion it shows the finished tree.

import {useEffect, useMemo, useRef, useState} from 'react';
import {joinClasses} from '../classes';
import {INITIAL_ELO} from './home_landing_content';
import {expectedScore} from './home_landing_elo';
import {type MotionProps, useInView} from './home_landing_hooks';

// Example hypotheses for a glioblastoma drug-repurposing goal, with the
// hidden strength that decides their debates.
const IDEAS: readonly {title: string; strength: number}[] = [
  {title: 'Metformin sensitizes GBM stem cells', strength: 0.9},
  {title: 'Valproate reprograms tumor microglia', strength: 0.45},
  {title: 'Statins trigger ferroptosis in GBM', strength: 0.7},
  {title: 'Chloroquine blocks autophagy rescue', strength: 0.55},
  {title: 'Disulfiram–copper targets ALDH+ cells', strength: 0.65},
  {title: 'Itraconazole halts Hedgehog signaling', strength: 0.4},
  {title: 'Mebendazole disrupts tumor microtubules', strength: 0.6},
  {title: 'Propranolol dampens stress signaling', strength: 0.35},
];

const K = 32;
const ROUNDS = 3;
const STEP_MS = 1600;
const LEAF_W = 400;
const ROW_H = 48;
const TOP = 26;
const ROUND_X = [LEAF_W + 110, LEAF_W + 260, LEAF_W + 410];
const CHAMP_X = LEAF_W + 470;

/** One debate: two contenders (idea indexes), the winner, and its y. */
interface Match {
  a: number;
  b: number;
  winner: number;
  y: number;
}

interface Bracket {
  rounds: Match[][];
  /** elo[step][i]: idea i's rating after `step` rounds. */
  elo: number[][];
  leafY: number[];
}

// Plays the whole tree once. The stronger idea wins each debate, which is
// what a real run's many matches converge on, and both ratings move.
function playBracket(): Bracket {
  const leafY = IDEAS.map((_, i) => TOP + i * ROW_H + ROW_H / 2);
  const elo = [IDEAS.map(() => INITIAL_ELO)];
  let field = IDEAS.map((_, i) => ({idea: i, y: leafY[i]}));
  const rounds: Match[][] = [];
  for (let r = 0; r < ROUNDS; r++) {
    const next = elo[r].slice();
    const round = pairUp(field).map(([p, q]) => {
      const winner = IDEAS[p.idea].strength >= IDEAS[q.idea].strength ? p : q;
      const loser = winner === p ? q : p;
      const delta =
        K * (1 - expectedScore(next[winner.idea], next[loser.idea]));
      next[winner.idea] += delta;
      next[loser.idea] -= delta;
      return {a: p.idea, b: q.idea, winner: winner.idea, y: (p.y + q.y) / 2};
    });
    rounds.push(round);
    elo.push(next);
    field = round.map(m => ({idea: m.winner, y: m.y}));
  }
  return {rounds, elo, leafY};
}

function pairUp<T>(items: T[]): [T, T][] {
  const pairs: [T, T][] = [];
  for (let i = 0; i < items.length; i += 2)
    pairs.push([items[i], items[i + 1]]);
  return pairs;
}

// Advances the tree a round at a time while on screen, holding the finished
// tree for two beats before replaying.
function useBracketStep(visible: boolean, reduceMotion: boolean): number {
  const [step, setStep] = useState(0);
  useEffect(() => {
    if (!visible || reduceMotion) return;
    const timer = window.setInterval(
      () => setStep(s => (s + 1) % (ROUNDS + 3)),
      STEP_MS,
    );
    return () => window.clearInterval(timer);
  }, [visible, reduceMotion]);
  return reduceMotion ? ROUNDS : Math.min(step, ROUNDS);
}

function xOfRound(round: number): number {
  return round < 0 ? LEAF_W : ROUND_X[round];
}

// The elbow from a contender (at the previous round's x) into its match.
function Connector({
  fromX,
  fromY,
  match,
  toX,
  won,
}: {
  fromX: number;
  fromY: number;
  match: Match;
  toX: number;
  won: boolean;
}) {
  const mid = fromX + (toX - fromX) / 2;
  return (
    <path
      className={joinClasses('ucs-landing-tree-wire', won && 'is-won')}
      d={`M${fromX} ${fromY} H${mid} V${match.y} H${toX - 14}`}
    />
  );
}

function RoundWires({
  bracket,
  round,
  step,
}: {
  bracket: Bracket;
  round: number;
  step: number;
}) {
  const fromY = (idea: number) =>
    round === 0
      ? bracket.leafY[idea]
      : (bracket.rounds[round - 1].find(m => m.winner === idea)?.y ?? 0);
  return (
    <>
      {bracket.rounds[round].flatMap(match =>
        // The loser first, so the winner's lit path draws over the shared
        // run into the match.
        [match.winner === match.a ? match.b : match.a, match.winner].map(
          idea => (
            <Connector
              key={`${round}-${idea}`}
              fromX={xOfRound(round - 1) + (round === 0 ? 0 : 14)}
              fromY={fromY(idea)}
              match={match}
              toX={xOfRound(round)}
              won={step > round && match.winner === idea}
            />
          ),
        ),
      )}
    </>
  );
}

function RoundNodes({
  bracket,
  round,
  step,
}: {
  bracket: Bracket;
  round: number;
  step: number;
}) {
  return (
    <>
      {bracket.rounds[round].map(match => (
        <g
          key={match.y}
          className={joinClasses(
            'ucs-landing-tree-node',
            step === round && 'is-live',
            step > round && 'is-done',
          )}
        >
          <circle cx={xOfRound(round)} cy={match.y} r="14" />
          <text x={xOfRound(round)} y={match.y + 5} textAnchor="middle">
            {step > round ? '' : 'vs'}
          </text>
        </g>
      ))}
    </>
  );
}

function Leaves({bracket, step}: {bracket: Bracket; step: number}) {
  const champion = bracket.rounds[ROUNDS - 1][0].winner;
  return (
    <>
      {IDEAS.map((idea, i) => (
        <g
          key={idea.title}
          className={joinClasses(
            'ucs-landing-tree-leaf',
            step === ROUNDS && i === champion && 'is-champion',
          )}
        >
          <rect
            x="0"
            y={bracket.leafY[i] - 19}
            width={LEAF_W}
            height="38"
            rx="20"
          />
          <text x="18" y={bracket.leafY[i] + 5}>
            {idea.title}
          </text>
          <text
            className="ucs-landing-tree-elo"
            x={LEAF_W - 16}
            y={bracket.leafY[i] + 5}
            textAnchor="end"
          >
            {Math.round(bracket.elo[step][i])}
          </text>
        </g>
      ))}
    </>
  );
}

function Champion({bracket, step}: {bracket: Bracket; step: number}) {
  const final = bracket.rounds[ROUNDS - 1][0];
  const shown = step === ROUNDS;
  return (
    <g className={joinClasses('ucs-landing-tree-champ', shown && 'is-shown')}>
      <path
        className="ucs-landing-tree-wire is-won"
        d={`M${xOfRound(ROUNDS - 1) + 14} ${final.y} H${CHAMP_X}`}
      />
      <rect x={CHAMP_X} y={final.y - 34} width="190" height="68" rx="34" />
      <text x={CHAMP_X + 95} y={final.y - 4} textAnchor="middle">
        Top ranked
      </text>
      <text
        className="ucs-landing-tree-elo"
        x={CHAMP_X + 95}
        y={final.y + 18}
        textAnchor="middle"
      >
        Elo {Math.round(bracket.elo[ROUNDS][final.winner])}
      </text>
    </g>
  );
}

/** The tournament tree panel. */
export function LandingBracket({reduceMotion}: MotionProps) {
  const ref = useRef<HTMLDivElement | null>(null);
  const visible = useInView(ref, {once: false, threshold: 0.3});
  const bracket = useMemo(playBracket, []);
  const step = useBracketStep(visible, reduceMotion);
  const rounds = Array.from({length: ROUNDS}, (_, r) => r);
  return (
    <div ref={ref} className="ucs-landing-panel ucs-landing-tree">
      <div className="ucs-landing-tree-head">
        <span>Example · glioblastoma drug repurposing</span>
        <span>
          {step === 0
            ? 'Every idea starts at Elo 1200'
            : `Round ${step} of ${ROUNDS}`}
        </span>
      </div>
      <div className="ucs-landing-tree-scroll">
        <svg
          viewBox={`0 0 ${CHAMP_X + 200} ${TOP * 2 + IDEAS.length * ROW_H}`}
          role="img"
          aria-label="Tournament tree: eight example hypotheses debate in pairs over three rounds. Each debate moves both ideas' Elo ratings, and the idea that wins every debate ends ranked first."
        >
          {rounds.map(r => (
            <RoundWires key={r} bracket={bracket} round={r} step={step} />
          ))}
          <Champion bracket={bracket} step={step} />
          {rounds.map(r => (
            <RoundNodes key={r} bracket={bracket} round={r} step={step} />
          ))}
          <Leaves bracket={bracket} step={step} />
        </svg>
      </div>
      <p className="ucs-landing-tree-note">
        A simplified picture. In a real run no idea is knocked out: ideas are
        paired many times, mostly with rivals of similar rating, and every
        debate moves both Elo ratings. The ranking is where the ratings settle.
      </p>
    </div>
  );
}
