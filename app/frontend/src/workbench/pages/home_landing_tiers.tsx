import {useRef, useState} from 'react';
import {
  DEFAULT_TIER,
  LANDING_TIERS,
  type LandingTier,
  MAX_POOL,
} from './home_landing_content';
import {
  type MotionProps,
  useSlidingIndicator,
  SlidingPill,
} from './home_landing_hooks';

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
