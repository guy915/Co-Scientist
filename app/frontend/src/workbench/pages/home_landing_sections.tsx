// The landing page's content sections, top to bottom after the hero and the
// tab rail: overview, how it works, tournament, evidence, safety, tiers, FAQ,
// and the closing call to action. See home_landing.tsx for the frame.

import {type ReactNode, type Ref, useRef} from 'react';
import {Icon, type IconName} from '@/components/icon';
import {joinClasses} from '../classes';
import moleculeArt from '../../assets/landing/molecule.webp';
import podiumArt from '../../assets/landing/podium.webp';
import shapesArt from '../../assets/landing/shapes.webp';
import {LandingArena} from './home_landing_arena';
import {
  FAQ,
  INITIAL_ELO,
  LANDING_AGENTS,
  LANDING_SAFETY,
  LANDING_SOURCES,
  LANDING_VERDICTS,
  type LandingTone,
  MAX_POOL,
} from './home_landing_content';
import {LandingDiagram} from './home_landing_diagram';
import {LandingEloChart} from './home_landing_elo_chart';
import {type MotionProps, useCountUp, useInView} from './home_landing_hooks';
import {type ShapeName, shapePath, useShapeMorph} from './home_landing_shapes';
import {LandingTiers} from './home_landing_tiers';

function SectionHeading({title, lede}: {title: string; lede?: string}) {
  return (
    <>
      <h2 className="ucs-landing-h2">{title}</h2>
      {lede && <p className="ucs-landing-lede">{lede}</p>}
    </>
  );
}

/** A Material shape with an icon centered on it. */
function ShapeBadge({
  shape,
  tone,
  icon,
  pathRef,
}: {
  shape: ShapeName;
  tone: LandingTone;
  icon: IconName;
  pathRef?: Ref<SVGPathElement>;
}) {
  return (
    <span className={joinClasses('ucs-landing-badge', `tone-${tone}`)}>
      <svg viewBox="0 0 100 100" aria-hidden="true">
        <path ref={pathRef} d={shapePath(shape)} />
      </svg>
      <Icon aria-hidden="true" name={icon} />
    </span>
  );
}

function Fact({
  value,
  label,
  start,
  reduceMotion,
}: {
  value: number;
  label: string;
  start: boolean;
  reduceMotion: boolean;
}) {
  const shown = useCountUp(value, start, reduceMotion);
  return (
    <div>
      <b>{start ? shown : value}</b>
      <span>{label}</span>
    </div>
  );
}

export function OverviewSection({reduceMotion}: MotionProps) {
  const ref = useRef<HTMLDivElement | null>(null);
  const seen = useInView(ref);
  return (
    <section className="ucs-landing-sec" id="landing-overview">
      <div className="ucs-landing-overview" ref={ref}>
        <div>
          <p className="ucs-landing-label">Overview</p>
          <p className="ucs-landing-statement">
            You bring a research goal.{' '}
            <span>
              <span className="ucs-landing-nowrap">Co-Scientist</span> brings a
              team of agents that generate, critique, rank, and evolve
              hypotheses.
            </span>
          </p>
        </div>
        <div className="ucs-landing-facts">
          <Fact
            value={7}
            label="specialist agents, coordinated by a Supervisor"
            start={seen}
            reduceMotion={reduceMotion}
          />
          <Fact
            value={INITIAL_ELO}
            label="starting Elo for every idea in the tournament"
            start={seen}
            reduceMotion={reduceMotion}
          />
          <Fact
            value={MAX_POOL}
            label="ideas explored in the largest run"
            start={seen}
            reduceMotion={reduceMotion}
          />
        </div>
      </div>
    </section>
  );
}

function AgentCard({
  agent,
  wide,
  reduceMotion,
}: {
  agent: (typeof LANDING_AGENTS)[number];
  wide: boolean;
  reduceMotion: boolean;
}) {
  const morph = useShapeMorph(agent.shape, reduceMotion);
  return (
    <article
      className={joinClasses('ucs-landing-agent', wide && 'is-wide')}
      tabIndex={0}
      onPointerEnter={morph.toCircle}
      onPointerLeave={morph.toRest}
      onFocus={morph.toCircle}
      onBlur={morph.toRest}
    >
      <ShapeBadge
        shape={agent.shape}
        tone={agent.tone}
        icon={agent.icon}
        pathRef={morph.pathRef}
      />
      <div>
        <h3>{agent.name}</h3>
        <p>{agent.summary}</p>
      </div>
    </article>
  );
}

export function HowSection({reduceMotion}: MotionProps) {
  return (
    <section className="ucs-landing-sec" id="landing-how">
      <SectionHeading
        title="How it works"
        lede="A Supervisor plans the run and hands work to six specialist agents. The loop repeats until the rankings settle, then you get a research overview back."
      />
      <LandingDiagram reduceMotion={reduceMotion} />
      <div className="ucs-landing-agents">
        {LANDING_AGENTS.map((agent, i) => (
          <AgentCard
            key={agent.name}
            agent={agent}
            wide={i === 0}
            reduceMotion={reduceMotion}
          />
        ))}
      </div>
    </section>
  );
}

export function TournamentSection({reduceMotion}: MotionProps) {
  return (
    <section className="ucs-landing-sec" id="landing-tournament">
      <SectionHeading
        title="Tournament"
        lede="Ideas meet in pairwise debates. Every win and loss moves their Elo rating, so the ranking reflects many arguments, not one score."
      />
      <LandingArena reduceMotion={reduceMotion} />
      <div className="ucs-landing-duo">
        <LandingEloChart reduceMotion={reduceMotion} />
        <div className="ucs-landing-panel ucs-landing-podium">
          <div>
            <h3>Ranked ideas</h3>
            <p>
              Every hypothesis comes back with its Elo rating, its reviews, and
              the ideas it was bred from.
            </p>
          </div>
          <img
            src={podiumArt}
            loading="lazy"
            decoding="async"
            alt="3D render: seven pedestals of falling height, the top three crowned with blue, teal and yellow spheres."
          />
        </div>
      </div>
    </section>
  );
}

// The sources the agents read, sliding past as outlined display type.
function SourcesMarquee() {
  const items = [...LANDING_SOURCES, ...LANDING_SOURCES];
  return (
    <div className="ucs-landing-marquee">
      <p className="ucs-landing-label">Built on the literature</p>
      <div className="ucs-landing-marquee-window" aria-hidden="true">
        <div className="ucs-landing-marquee-track">
          {items.map((source, i) => (
            <span key={i} className={i % 3 === 0 ? 'is-solid' : undefined}>
              {source}
            </span>
          ))}
        </div>
      </div>
      <p className="ucs-landing-sr-only">
        Sources: {LANDING_SOURCES.join(', ')}.
      </p>
    </div>
  );
}

export function EvidenceSection() {
  return (
    <section className="ucs-landing-sec" id="landing-evidence">
      <SectionHeading title="Evidence" />
      <div className="ucs-landing-evidence">
        <svg
          className="ucs-landing-specimen tone-green"
          viewBox="0 0 100 100"
          role="img"
          aria-label="3D render of a small-molecule drug inside a flower shape."
        >
          <defs>
            <clipPath id="ucs-landing-flower">
              <path d={shapePath('flower')} />
            </clipPath>
          </defs>
          <path d={shapePath('flower')} />
          <image
            href={moleculeArt}
            x="14"
            y="30"
            width="72"
            height="40"
            clipPath="url(#ucs-landing-flower)"
            preserveAspectRatio="xMidYMid meet"
          />
        </svg>
        <div>
          <p className="ucs-landing-lede">
            Each hypothesis is split into atomic claims. Passages from the
            literature are matched to every claim and judged before the idea may
            enter the tournament.
          </p>
          <div className="ucs-landing-verdicts">
            {LANDING_VERDICTS.map(v => (
              <div key={v.label} className={`tone-${v.tone}`}>
                <b>{v.label}</b>
                <span>{v.body}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
      <SourcesMarquee />
    </section>
  );
}

export function SafetySection() {
  return (
    <section className="ucs-landing-sec" id="landing-safety">
      <SectionHeading title="Safety" />
      <div className="ucs-landing-safety">
        {LANDING_SAFETY.map(layer => (
          <div key={layer.title}>
            <ShapeBadge
              shape={layer.shape}
              tone={layer.tone}
              icon={layer.icon}
            />
            <h3>{layer.title}</h3>
            <p>{layer.body}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

export function TiersSection({reduceMotion}: MotionProps) {
  return (
    <section className="ucs-landing-sec" id="landing-tiers">
      <SectionHeading
        title="Tiers"
        lede="Choose a tier when you start. It sets how many ideas are seeded, how many evolution cycles run, and how large the pool can grow."
      />
      <LandingTiers reduceMotion={reduceMotion} />
    </section>
  );
}

export function FaqSection() {
  return (
    <section className="ucs-landing-sec" id="faq">
      <SectionHeading title="Questions" />
      <div className="ucs-landing-faq">
        {FAQ.map((entry, i) => (
          <details key={entry.question} open={i === 0}>
            <summary>
              <span>{entry.question}</span>
              <Icon aria-hidden="true" name="expand_more" />
            </summary>
            <p>{entry.answer}</p>
          </details>
        ))}
      </div>
    </section>
  );
}

export function ClosingSection({onStart}: {onStart: () => void}): ReactNode {
  return (
    <section className="ucs-landing-sec ucs-landing-sec--tight">
      <div className="ucs-landing-cta">
        <div>
          <h2 className="ucs-landing-h2">Start with a question.</h2>
          <p>
            Describe what you want to find out.{' '}
            <span className="ucs-landing-nowrap">Co-Scientist</span> asks what a
            strong answer needs, then sends its agents to work.
          </p>
          <button
            type="button"
            className="ucs-landing-pill is-solid"
            onClick={onStart}
          >
            Start a research goal
          </button>
        </div>
        <img
          src={shapesArt}
          loading="lazy"
          decoding="async"
          alt="3D render of glossy Material shapes: a teal scalloped cookie, green clover, yellow flower, blue sunny shape and a red sphere."
        />
      </div>
    </section>
  );
}
