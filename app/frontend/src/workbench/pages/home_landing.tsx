// The landing page below the chat home. The home still opens exactly as it
// always has; a quiet hint under the composer (see chat_home_stage.tsx)
// invites a scroll, and this page explains the system: a hero with the
// wordmark, a sticky tab rail, then the sections in home_landing_sections.
// Lazy-loaded by the home stage so none of it weighs on the first paint.

import {
  type MouseEvent,
  type RefObject,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import {useLocation} from 'react-router-dom';
import helixArt from '../../assets/landing/helix.webp';
import {joinClasses} from '../classes';
import {LANDING_SECTIONS} from './home_landing_content';
import {
  scrollParent,
  useReducedMotion,
  useSlidingIndicator,
} from './home_landing_hooks';
import {SlidingPill} from './home_landing_slider';
import {
  ClosingSection,
  EvidenceSection,
  FaqSection,
  HowSection,
  SafetySection,
  TiersSection,
  TournamentSection,
} from './home_landing_sections';
import {OverviewSection} from './home_landing_overview';
import {shapePath} from './home_landing_shapes';

/** The landing page's root id, which the scroll hint links to. */
export const LANDING_ID = 'landing';

const COMPOSER_SELECTOR = '.reference-composer textarea';

function scrollBehavior(reduceMotion: boolean): ScrollBehavior {
  return reduceMotion ? 'auto' : 'smooth';
}

/** Scrolls the landing section with `id` into view. */
export function scrollToLandingSection(id: string, reduceMotion: boolean) {
  document
    .getElementById(id)
    ?.scrollIntoView({behavior: scrollBehavior(reduceMotion), block: 'start'});
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
