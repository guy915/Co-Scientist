import {
  type MouseEvent,
  type RefObject,
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
  type Ref,
} from 'react';
import {useLocation} from 'react-router-dom';
import {smoothScrollToSection} from '@/lib/smooth_scroll';
import helixArt from '../../assets/landing/helix.webp';
import {joinClasses} from '../classes';
import {
  LANDING_SECTIONS,
  FAQ,
  LANDING_AGENTS,
  LANDING_SAFETY,
  LANDING_SOURCES,
  LANDING_VERDICTS,
  type LandingTone,
  DEFAULT_TIER,
  LANDING_TIERS,
  type LandingTier,
  MAX_POOL,
} from './home_landing_content';
import {
  scrollParent,
  useReducedMotion,
  useSlidingIndicator,
  SlidingPill,
  shapePath,
  type MotionProps,
  type ShapeName,
  useShapeMorph,
  useInView,
} from './home_landing_hooks';
import {Icon, type IconName} from '@/components/icon';
import moleculeArt from '../../assets/landing/molecule.webp';
import podiumArt from '../../assets/landing/podium.webp';
import flaskArt from '../../assets/landing/flask.webp';
import {
  LandingBracket,
  LandingDiagram,
  LandingEloChart,
} from './home_landing_diagram';
import {SUGGESTIONS} from './chat_home_stage';

// The landing page below the chat home. The home still opens exactly as it
// always has; a quiet hint under the composer (see chat_home_stage.tsx)
// invites a scroll, and this page explains the system: a hero with the
// wordmark, a sticky tab rail, then the sections in home_landing_sections.
// Lazy-loaded by the home stage so none of it weighs on the first paint.

/** The landing page's root id, which the scroll hint links to. */
export const LANDING_ID = 'landing';

const COMPOSER_SELECTOR = '.reference-composer textarea';

function scrollBehavior(reduceMotion: boolean): ScrollBehavior {
  return reduceMotion ? 'auto' : 'smooth';
}

// The home page's own scroll pane. Scrolling it directly (never with
// scrollIntoView, which also scrolls the shell's clipped ancestors and
// leaves the whole app shifted up) keeps the shell in place.
const HOME_SCROLLER = '.ucs-page--home';

// Room left above a section for the sticky rail.
const RAIL_OFFSET = 72;

/** Scrolls the landing section with `id` to just under the rail. */
export function scrollToLandingSection(id: string, reduceMotion: boolean) {
  smoothScrollToSection(
    id,
    RAIL_OFFSET,
    HOME_SCROLLER,
    scrollBehavior(reduceMotion),
  );
}

// Scrolls back up to the home stage and puts the caret in the composer.
function useStartResearch(
  rootRef: RefObject<HTMLElement | null>,
  reduceMotion: boolean,
) {
  return useCallback(() => {
    scrollParent(rootRef.current).scrollTo({
      top: 0,
      behavior: scrollBehavior(reduceMotion),
    });
    window.setTimeout(
      () =>
        document
          .querySelector<HTMLTextAreaElement>(COMPOSER_SELECTOR)
          ?.focus({preventScroll: true}),
      reduceMotion ? 0 : 600,
    );
  }, [rootRef, reduceMotion]);
}

function LandingHero({
  onStart,
  reduceMotion,
}: {
  onStart: () => void;
  reduceMotion: boolean;
}) {
  const cookie = shapePath('cookie12');
  return (
    <section className="ucs-landing-hero" aria-labelledby="ucs-landing-word">
      <h2 id="ucs-landing-word" className="ucs-landing-word">
        Co-Scientist
      </h2>
      <div className="ucs-landing-hero-grid">
        <div className="ucs-landing-hero-copy">
          <p>A multi-agent partner for scientific discovery.</p>
          <div className="ucs-landing-pills">
            <button
              type="button"
              className="ucs-landing-pill is-solid"
              onClick={onStart}
            >
              Start a research goal
            </button>
            <button
              type="button"
              className="ucs-landing-pill is-line"
              onClick={() =>
                scrollToLandingSection('landing-how', reduceMotion)
              }
            >
              See how it works
            </button>
          </div>
        </div>
        <svg
          className="ucs-landing-hero-art tone-teal"
          viewBox="0 0 100 100"
          role="img"
          aria-label="3D render of a DNA double helix whose base pairs are blue, red, yellow and green, inside a scalloped cookie shape."
        >
          <defs>
            <clipPath id="ucs-landing-cookie">
              <path className="ucs-landing-spin" d={cookie} />
            </clipPath>
          </defs>
          <path className="ucs-landing-spin" d={cookie} />
          <image
            href={helixArt}
            x="6"
            y="6"
            width="88"
            height="88"
            clipPath="url(#ucs-landing-cookie)"
            preserveAspectRatio="xMidYMid meet"
          />
        </svg>
      </div>
    </section>
  );
}

// Follows which section is under the rail, so its tab can light up.
function useActiveSection(): string {
  const [active, setActive] = useState(LANDING_SECTIONS[0].id);
  useEffect(() => {
    if (typeof IntersectionObserver === 'undefined') return;
    const observer = new IntersectionObserver(
      entries => {
        const hit = entries.find(entry => entry.isIntersecting);
        if (hit) setActive(hit.target.id);
      },
      {rootMargin: '-30% 0px -65% 0px'},
    );
    for (const {id} of LANDING_SECTIONS) {
      const el = document.getElementById(id);
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, []);
  return active;
}

// Scrolls an overflowing rail so the tab for section `id` sits centered.
function centerTab(nav: HTMLElement, id: string, reduceMotion: boolean) {
  const tab = nav.querySelector<HTMLElement>(`[data-section="${id}"]`);
  if (!tab || nav.scrollWidth <= nav.clientWidth) return;
  const left = tab.offsetLeft - (nav.clientWidth - tab.offsetWidth) / 2;
  nav.scrollTo?.({left, behavior: scrollBehavior(reduceMotion)});
}

// Keeps the active tab in view on a narrow rail, and fades the rail's edge
// only while more tabs are hidden past it.
function useRailScroll(
  navRef: RefObject<HTMLElement | null>,
  active: string,
  reduceMotion: boolean,
) {
  const [more, setMore] = useState(false);
  useEffect(() => {
    const nav = navRef.current;
    if (!nav) return;
    const update = () =>
      setMore(nav.scrollLeft + nav.clientWidth < nav.scrollWidth - 4);
    update();
    nav.addEventListener('scroll', update, {passive: true});
    window.addEventListener('resize', update);
    return () => {
      nav.removeEventListener('scroll', update);
      window.removeEventListener('resize', update);
    };
  }, [navRef]);
  useEffect(() => {
    if (navRef.current) centerTab(navRef.current, active, reduceMotion);
  }, [navRef, active, reduceMotion]);
  return more;
}

function LandingRail({reduceMotion}: {reduceMotion: boolean}) {
  const active = useActiveSection();
  const navRef = useRef<HTMLElement | null>(null);
  const more = useRailScroll(navRef, active, reduceMotion);
  const pill = useSlidingIndicator(navRef, '.is-active', active);
  const go = (e: MouseEvent<HTMLAnchorElement>, id: string) => {
    e.preventDefault();
    scrollToLandingSection(id, reduceMotion);
  };
  return (
    <div className="ucs-landing-rail">
      <nav
        ref={navRef}
        aria-label="Landing sections"
        className={joinClasses(more && 'has-more')}
      >
        <SlidingPill box={pill} />
        {LANDING_SECTIONS.map(({id, label}) => (
          <a
            key={id}
            href={`#${id}`}
            data-section={id}
            className={joinClasses(active === id && 'is-active')}
            aria-current={active === id ? 'true' : undefined}
            onClick={e => go(e, id)}
          >
            {label}
          </a>
        ))}
      </nav>
    </div>
  );
}

// Opening the app on /#faq (the Settings > Help link) lands on the FAQ.
function useHashLanding(reduceMotion: boolean) {
  const {hash, key} = useLocation();
  useEffect(() => {
    const id = hash.slice(1);
    if (!LANDING_SECTIONS.some(section => section.id === id)) return;
    const timer = window.setTimeout(
      () => scrollToLandingSection(id, reduceMotion),
      50,
    );
    return () => window.clearTimeout(timer);
  }, [hash, key, reduceMotion]);
}

/** The landing page, rendered under the home stage. */
export default function HomeLanding() {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const reduceMotion = useReducedMotion();
  const onStart = useStartResearch(rootRef, reduceMotion);
  useHashLanding(reduceMotion);
  return (
    <div ref={rootRef} id={LANDING_ID} className="ucs-landing">
      <LandingHero onStart={onStart} reduceMotion={reduceMotion} />
      <LandingRail reduceMotion={reduceMotion} />
      <div className="ucs-landing-body">
        <OverviewSection reduceMotion={reduceMotion} />
        <HowSection reduceMotion={reduceMotion} />
        <TournamentSection reduceMotion={reduceMotion} />
        <EvidenceSection />
        <SafetySection reduceMotion={reduceMotion} />
        <TiersSection reduceMotion={reduceMotion} />
        <ClosingSection onStart={onStart} />
        <FaqSection />
      </div>
    </div>
  );
}

// The landing page's content sections, top to bottom after the hero and the
// tab rail: how it works, tournament, evidence, safety, tiers, the closing
// call to action, and the FAQ. The overview is home_landing_overview.tsx. See home_landing.tsx for the frame.

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
      <LandingBracket reduceMotion={reduceMotion} />
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

// The landing page's Overview: one run from end to end, as a worked example.
// What you write, what the agents do with it (the stages light up in order
// when the section comes into view), and what you get back.

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

// The Tiers section's interactive pool: a segmented control picks a tier,
// and a field of MAX_POOL dots fills in to that tier's size, colored by the
// evolution cycle each idea could arrive in. The numbers are the product's
// own RUN_TIER_DEFAULTS (see home_landing_content.ts).

// Seed ideas first, then each cycle's share of the remaining headroom.
function dotGeneration(tier: LandingTier, index: number): number | null {
  if (index < tier.seeds) return 0;
  if (index >= tier.maxIdeas) return null;
  const perCycle = (tier.maxIdeas - tier.seeds) / tier.cycles;
  return Math.min(tier.cycles, 1 + Math.floor((index - tier.seeds) / perCycle));
}

const GENERATIONS = [
  {label: 'Seed ideas', generation: 0},
  {label: 'Cycle 1', generation: 1},
  {label: 'Cycle 2', generation: 2},
  {label: 'Cycle 3', generation: 3},
  {label: 'Cycle 4', generation: 4},
];

function TierField({tier, reduceMotion}: {tier: LandingTier} & MotionProps) {
  return (
    <div>
      <div className="ucs-landing-field" aria-hidden="true">
        {Array.from({length: MAX_POOL}, (_, i) => {
          const generation = dotGeneration(tier, i);
          return (
            <i
              key={i}
              className={generation === null ? undefined : `g${generation}`}
              style={{transitionDelay: reduceMotion ? '0ms' : `${i * 6}ms`}}
            />
          );
        })}
      </div>
      <div className="ucs-landing-gens">
        {GENERATIONS.filter(g => g.generation <= tier.cycles).map(g => (
          <span key={g.label} className={`g${g.generation}`}>
            {g.label}
          </span>
        ))}
      </div>
    </div>
  );
}

function TierStats({tier}: {tier: LandingTier}) {
  return (
    <div className="ucs-landing-tier-stats" aria-live="polite">
      <div>
        <b>{tier.maxIdeas}</b>
        <span>ideas at most</span>
      </div>
      <div>
        <b>{tier.seeds}</b>
        <span>seed ideas</span>
      </div>
      <div>
        <b>{tier.cycles}</b>
        <span>
          {tier.cycles === 1 ? 'evolution cycle' : 'evolution cycles'}
        </span>
      </div>
    </div>
  );
}

/** The tier picker and its pool visualization. */
export function LandingTiers({reduceMotion}: MotionProps) {
  const [name, setName] = useState(DEFAULT_TIER);
  const tier = LANDING_TIERS.find(t => t.name === name) ?? LANDING_TIERS[1];
  const trackRef = useRef<HTMLDivElement | null>(null);
  const pill = useSlidingIndicator(trackRef, '[aria-pressed="true"]', name);
  return (
    <>
      <div
        ref={trackRef}
        className="ucs-landing-seg"
        role="group"
        aria-label="Run tier"
      >
        <SlidingPill box={pill} />
        {LANDING_TIERS.map(t => (
          <button
            key={t.name}
            type="button"
            aria-pressed={t.name === name}
            onClick={() => setName(t.name)}
          >
            {t.name}
          </button>
        ))}
      </div>
      <div className="ucs-landing-tierbox">
        <TierField tier={tier} reduceMotion={reduceMotion} />
        <TierStats tier={tier} />
      </div>
    </>
  );
}
