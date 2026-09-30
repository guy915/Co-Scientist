// The landing page's content sections, top to bottom after the hero and the
// tab rail: how it works, tournament, evidence, safety, tiers, the closing
// call to action, and the FAQ. The overview is home_landing_overview.tsx. See home_landing.tsx for the frame.

import {type ReactNode, type Ref} from 'react';
import {Icon, type IconName} from '@/components/icon';
import {joinClasses} from '../classes';
import moleculeArt from '../../assets/landing/molecule.webp';
import podiumArt from '../../assets/landing/podium.webp';
import flaskArt from '../../assets/landing/flask.webp';
import {LandingBracket} from './home_landing_bracket';
import {
  FAQ,
  LANDING_AGENTS,
  LANDING_SAFETY,
  LANDING_SOURCES,
  LANDING_VERDICTS,
  type LandingTone,
} from './home_landing_content';
import {LandingDiagram} from './home_landing_diagram';
import {LandingEloChart} from './home_landing_elo_chart';
import {type MotionProps} from './home_landing_hooks';
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
      <LandingDiagram />
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
      <LandingBracket />
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

// The sources the agents read, sliding past in display type.
function SourcesMarquee() {
  const items = [...LANDING_SOURCES, ...LANDING_SOURCES];
  return (
    <div className="ucs-landing-marquee">
      <p className="ucs-landing-label">Built on the literature</p>
      <div className="ucs-landing-marquee-window" aria-hidden="true">
        <div className="ucs-landing-marquee-track">
          {items.map((source, i) => (
            <span key={i}>{source}</span>
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

// A safety layer's card; its shape morphs to a circle on hover or focus,
// the same response as the agent cards.
function SafetyCard({
  layer,
  reduceMotion,
}: {
  layer: (typeof LANDING_SAFETY)[number];
  reduceMotion: boolean;
}) {
  const morph = useShapeMorph(layer.shape, reduceMotion);
  return (
    <article
      tabIndex={0}
      onPointerEnter={morph.toCircle}
      onPointerLeave={morph.toRest}
      onFocus={morph.toCircle}
      onBlur={morph.toRest}
    >
      <ShapeBadge
        shape={layer.shape}
        tone={layer.tone}
        icon={layer.icon}
        pathRef={morph.pathRef}
      />
      <h3>{layer.title}</h3>
      <p>{layer.body}</p>
    </article>
  );
}

export function SafetySection({reduceMotion}: MotionProps) {
  return (
    <section className="ucs-landing-sec" id="landing-safety">
      <SectionHeading title="Safety" />
      <div className="ucs-landing-safety">
        {LANDING_SAFETY.map(layer => (
          <SafetyCard
            key={layer.title}
            layer={layer}
            reduceMotion={reduceMotion}
          />
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
        {FAQ.map(entry => (
          <details key={entry.question}>
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
          src={flaskArt}
          loading="lazy"
          decoding="async"
          alt="3D render of a glass Erlenmeyer flask holding a glowing teal liquid."
        />
      </div>
    </section>
  );
}
