// The landing page's Overview: one run from end to end, as a worked example.
// What you write, what the agents do with it (the stages light up in order
// when the section comes into view), and what you get back.

import {useEffect, useRef, useState} from 'react';
import {Icon, type IconName} from '@/components/icon';
import {joinClasses} from '../classes';
import {SUGGESTIONS} from './chat_home_stage';
import {type MotionProps, useInView} from './home_landing_hooks';

const STAGES: readonly {icon: IconName; label: string}[] = [
  {icon: 'menu_book', label: 'Reads the literature on your goal'},
  {icon: 'lightbulb', label: 'Writes candidate hypotheses'},
  {
    icon: 'rate_review',
    label: 'Reviews each for correctness, novelty and testability',
  },
  {icon: 'leaderboard', label: 'Ranks them in an Elo tournament of debates'},
  {icon: 'genetics', label: 'Evolves the strongest into better ideas'},
  {icon: 'summarize', label: 'Writes a research overview'},
];

const STAGE_MS = 700;

// The first home suggestion's full prompt: its title line and the first
// paragraph of what it asks for.
const [GOAL_TITLE, GOAL_BODY] = SUGGESTIONS[0].prompt.split('\n\n');

// Example output for that goal: the top three ideas of a finished run.
const RANKED: readonly {title: string; elo: number}[] = [
  {
    title: 'Metformin sensitizes glioblastoma stem cells to temozolomide',
    elo: 1287,
  },
  {title: 'Statins trigger ferroptosis in GBM', elo: 1241},
  {title: 'Disulfiram–copper targets ALDH+ cells', elo: 1226},
];

// Lights the stages one by one once the section is seen.
function useLitStages(seen: boolean, reduceMotion: boolean): number {
  const [lit, setLit] = useState(0);
  useEffect(() => {
    if (!seen || reduceMotion) return;
    const timer = window.setInterval(
      () => setLit(n => Math.min(n + 1, STAGES.length)),
      STAGE_MS,
    );
    return () => window.clearInterval(timer);
  }, [seen, reduceMotion]);
  return reduceMotion ? STAGES.length : lit;
}

function InputCard() {
  return (
    <div className="ucs-landing-ov-card">
      <h3>You write</h3>
      <p className="ucs-landing-ov-sub">
        A research goal in plain language. Add your own papers and choose the
        sources to search if you like.
      </p>
      <div className="ucs-landing-ov-goal">
        <b>{GOAL_TITLE}</b>
        <p>{GOAL_BODY}</p>
        <div className="ucs-landing-ov-chips">
          <span className="tone-blue">PubMed</span>
          <span className="tone-blue">Europe PMC</span>
          <span className="tone-teal">Standard tier</span>
        </div>
      </div>
    </div>
  );
}

function RunCard({lit}: {lit: number}) {
  return (
    <div className="ucs-landing-ov-card">
      <h3>The agents</h3>
      <p className="ucs-landing-ov-sub">
        Work through the goal in a loop, as many cycles as the tier allows.
      </p>
      <ol className="ucs-landing-ov-stages">
        {STAGES.map((stage, i) => (
          <li key={stage.label} className={joinClasses(i < lit && 'is-lit')}>
            <Icon aria-hidden="true" name={stage.icon} />
            <span>{stage.label}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function OutputCard() {
  return (
    <div className="ucs-landing-ov-card">
      <h3>You get</h3>
      <p className="ucs-landing-ov-sub">
        Ranked hypotheses, each with its reviews, Elo rating, and claims checked
        against sources, plus a report you can share.
      </p>
      <div className="ucs-landing-ov-idea">
        <div className="ucs-landing-ov-idea-meta">
          <span>#1</span>
          <span>Elo {RANKED[0].elo}</span>
        </div>
        <b>{RANKED[0].title}</b>
        <div className="ucs-landing-ov-chips">
          <span className="tone-green">Supports 3</span>
          <span className="tone-yellow">Partial 1</span>
        </div>
      </div>
      <ol className="ucs-landing-ov-rest" start={2}>
        {RANKED.slice(1).map((idea, i) => (
          <li key={idea.title}>
            <span>#{i + 2}</span>
            <span>{idea.title}</span>
            <span>{idea.elo}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

export function OverviewSection({reduceMotion}: MotionProps) {
  const ref = useRef<HTMLDivElement | null>(null);
  const seen = useInView(ref, {threshold: 0.3});
  const lit = useLitStages(seen, reduceMotion);
  return (
    <section className="ucs-landing-sec" id="landing-overview">
      <h2 className="ucs-landing-h2">From a question to ranked ideas</h2>
      <p className="ucs-landing-lede">
        One run, end to end. The example uses the first suggestion on the home
        screen; the output shown is illustrative.
      </p>
      <div className="ucs-landing-ov" ref={ref}>
        <InputCard />
        <RunCard lit={lit} />
        <OutputCard />
      </div>
    </section>
  );
}
