import React from 'react';
import {AbsoluteFill, spring, useCurrentFrame} from 'remotion';
import {SEEDS} from '../data/demo_run';
import {Caption} from '../glide/Run';
import {FloatCard} from '../shared/FloatCard';
import {WordReveal} from '../shared/WordReveal';
import {type Pose, FPS, accel, emphasized, mix, posed, ramp} from '../shared/motion';
import {C, FONT, MONO} from '../shared/tokens';
import {Cuts, useBeats} from './Beat';
import {Sfx} from './Sfx';

// The app's left icon rail reads as a stray sliver once a screen is floated.
const NO_RAIL = {x: 0.03, y: 0, w: 0.97, h: 1};
// The ideas screen's #1 card, in px of the 1500-wide card from its centre, and its size.
const TOP = {x: -520, y: -199, w: 374, h: 135};

/**
 * Beats 41-47: three real screens fan out in depth around the ranked list,
 * then the camera pushes into the #1 idea, landing on the 28.7 s stab (beat 4)
 * where its ring and rating pop.
 */
export const Ranked: React.FC = () => {
  const f = useCurrentFrame();
  const b = useBeats();
  const push = b(2.5);
  const land = b(4);
  const side = (dir: number, at: number): Pose[] => [
    {f: at, x: 0, ry: 0, scale: 0.7, opacity: 0},
    {f: at + 14, x: dir * 560, ry: dir * -26, scale: 0.66, opacity: 1, glow: 0.5},
    {f: push, x: dir * 600, scale: 0.68},
    {f: push + 16, x: dir * 1500, opacity: 0},
  ];
  // x and y stay proportional to scale through the push, so the #1 card ends centred and stays there.
  const center: Pose[] = [
    {f: 0, y: 380, rx: 22, scale: 0.56, opacity: 0},
    {f: 16, y: 0, rx: 0, scale: 0.6, opacity: 1},
    {f: push, scale: 0.64},
    {f: land, x: -TOP.x * 2.2, y: -TOP.y * 2.2, scale: 2.2, glow: 0.2},
    {f: b(6), x: -TOP.x * 2.3, y: -TOP.y * 2.3, scale: 2.3},
  ];
  const cam = posed(f, center);
  const pop = spring({frame: f - land, fps: FPS, config: {damping: 12, stiffness: 170}});
  const ringW = TOP.w * cam.scale + 36;
  return (
    <AbsoluteFill>
      <FloatCard src="ui/light-details.png" width={1100} crop={NO_RAIL} blur={2} {...posed(f, side(-1, b(0.5)))} />
      <FloatCard src="ui/light-overview.png" width={1100} crop={NO_RAIL} blur={2} {...posed(f, side(1, b(1)))} />
      <FloatCard src="ui/light-ideas.png" width={1500} crop={NO_RAIL} {...cam} />
      {/* The ring's spread shadow is a white scrim with the #1 card cut out of it: a spotlight the chip can sit on. */}
      {f >= land && (
        <>
          <div style={{position: 'absolute', left: 960 - ringW / 2, top: 540 - (TOP.h * cam.scale + 36) / 2, width: ringW, height: TOP.h * cam.scale + 36, boxSizing: 'border-box', borderRadius: 34, border: `7px solid ${C.teal}`, boxShadow: `0 0 0 3000px rgba(255,255,255,${0.72 * Math.min(1, pop * 1.5)})`, transform: `scale(${mix(1.12, 1, pop)})`}} />
          <div style={{position: 'absolute', left: 960 + ringW / 2 + 34, top: 540 - 38, fontFamily: MONO, fontSize: 42, fontWeight: 500, color: '#fff', background: C.teal, padding: '14px 32px', borderRadius: 999, whiteSpace: 'nowrap', transform: `scale(${pop})`, transformOrigin: 'left center'}}>
            #1 · Elo {SEEDS[0].elo}
          </div>
        </>
      )}
      <Caption text="Every idea ranked in a head-to-head tournament." start={4} end={push} />
      <Sfx at={2} name="whoosh" volume={0.45} />
      <Sfx at={b(0.5)} name="pop1" volume={0.4} />
      <Sfx at={b(1)} name="pop2" volume={0.4} />
      <Sfx at={push} name="swish" volume={0.45} />
      <Sfx at={land} name="ding" volume={0.55} />
      <Sfx at={land + 3} name="pop6" volume={0.45} />
    </AbsoluteFill>
  );
};

// Sources are real tools the reference MCP server exposes.
const SOURCES = ['PubMed', 'UniProt', 'Reactome', 'ClinicalTrials.gov', 'Open Targets', 'ChEMBL'];
const CLAIMS = [
  {w: 600, verdict: 'supports', tone: C.container.green, ink: C.on.green},
  {w: 520, verdict: 'partial', tone: C.container.yellow, ink: C.on.yellow},
  {w: 560, verdict: 'supports', tone: C.container.green, ink: C.on.green},
];

/** A's verdict card: the sources line up on eighths, then each verdict pops on a beat. */
const Verdicts: React.FC = () => {
  const f = useCurrentFrame();
  const b = useBeats();
  const card = spring({frame: f - 2, fps: FPS, config: {damping: 15, stiffness: 140}});
  const chips = [b(2), b(2.5), b(3)];
  const sources = SOURCES.map((_, i) => b(0.5 + i * 0.25));
  return (
    <AbsoluteFill style={{alignItems: 'center'}}>
      <div style={{marginTop: 110}}>
        <WordReveal text="Claims checked against the *literature.*" start={0} size={88} stagger={2} />
      </div>
      <div style={{marginTop: 60, width: 1100, borderRadius: 32, background: '#fff', boxShadow: '0 0 0 2px rgba(31,31,31,0.06), 0 30px 70px rgba(31,31,31,0.10)', padding: '44px 54px', transform: `translateY(${mix(70, 0, card)}px)`, opacity: Math.min(1, card * 1.5), fontFamily: FONT}}>
        <div style={{fontSize: 44, fontWeight: 500, color: C.ink}}>Metabolic wake-up before vancomycin exposure</div>
        {CLAIMS.map((c, i) => {
          const chip = spring({frame: f - chips[i], fps: FPS, config: {damping: 11, stiffness: 180}});
          return (
            <div key={i} style={{display: 'flex', alignItems: 'center', gap: 28, marginTop: 30}}>
              <div style={{height: 18, width: c.w, borderRadius: 9, background: '#E3E8EC'}} />
              <div style={{fontFamily: MONO, fontSize: 34, padding: '10px 26px', borderRadius: 999, background: c.tone, color: c.ink, transform: `scale(${chip})`}}>{c.verdict}</div>
            </div>
          );
        })}
      </div>
      <div style={{display: 'flex', gap: 18, marginTop: 50}}>
        {SOURCES.map((s, i) => {
          const t = ramp(f, sources[i], 8, emphasized);
          return (
            <div key={s} style={{fontFamily: FONT, fontSize: 34, color: C.inkSoft, padding: '14px 30px', borderRadius: 999, background: C.paperTint, opacity: t, transform: `translateY(${mix(20, 0, t)}px)`}}>
              {s}
            </div>
          );
        })}
      </div>
      <Sfx at={2} name="swish" volume={0.4} />
      {sources.map(s => <Sfx key={s} at={s} name="tick" volume={0.55} />)}
      {chips.map((c, i) => <Sfx key={c} at={c} name={`pop${[3, 2, 4][i]}`} volume={0.4} />)}
    </AbsoluteFill>
  );
};

// The leader's Provenance section in the real app: its one assessed claim,
// the verdict and the cited source. Fractions of the 1600x1000 capture.
const CLAIM_CROP = {x: 0.32, y: 0.505, w: 0.5, h: 0.27};

/** The same check in the real app, the verdict line underlined on the downbeat. */
const RealClaim: React.FC = () => {
  const f = useCurrentFrame();
  const inn = ramp(f, 0, 14, emphasized);
  const mark = ramp(f, 6, 12, emphasized);
  // The "Claim evidence" row inside the 1500-wide card (crop-relative 0.03-0.56 x, 0.62 y).
  return (
    <AbsoluteFill>
      <FloatCard src="ui/light-ideas.png" width={1500} crop={CLAIM_CROP} y={mix(60, 0, inn)} scale={1 + f * 0.001} opacity={inn} fade />
      <div style={{position: 'absolute', left: 252, top: 540 - 253 + 0.62 * 506 + 4, width: 790 * mark, height: 6, borderRadius: 3, background: C.teal}} />
      <Sfx at={0} name="shutter" volume={0.5} />
      <Sfx at={6} name="blip5" volume={0.35} />
    </AbsoluteFill>
  );
};

/** Beats 47-53: verdicts on the 31.2 s stab, then the same check in the real app. */
export const Evidence: React.FC = () => {
  const b = useBeats();
  return (
    <Cuts at={[0, b(4)]}>
      <Verdicts />
      <RealClaim />
    </Cuts>
  );
};

// Fractions of the 1600x1000 captures: the learning tab's knowledge base, and
// the overview tab's summary row.
const LEARN_CROP = {x: 0.22, y: 0.22, w: 0.62, h: 0.42};
const REPORT_CROP = {x: 0.215, y: 0.23, w: 0.61, h: 0.25};

/** Beats 53-57: the run's knowledge base, then its report, which pinches to a blurred pill to hand off to the drop. */
export const Report: React.FC = () => {
  const f = useCurrentFrame();
  const b = useBeats();
  const cut = b(2);
  const local = f - cut;
  const pinch = ramp(f, b(3) - 6, b(4) - b(3) + 6, accel);
  return (
    <AbsoluteFill>
      {f < cut ? (
        <FloatCard src="ui/light-learning.png" width={1560} crop={LEARN_CROP} y={mix(150, 70, ramp(f, 0, 16, emphasized))} scale={1 + f * 0.0015} opacity={ramp(f, 0, 8)} fade />
      ) : (
        <FloatCard src="ui/light-overview.png" width={1500} crop={REPORT_CROP} y={90} scale={(1 + local * 0.001) * mix(1, 0.3, pinch)} opacity={1 - pinch * 0.6} blur={pinch * 40} glow={mix(0.9, 1.4, pinch)} />
      )}
      <Caption text="Every run ends in a report you can act on." start={2} end={b(3) - 6} />
      <Sfx at={0} name="shutter" volume={0.6} />
      <Sfx at={8} name="whoosh" volume={0.45} />
      <Sfx at={cut} name="shutter" volume={0.75} />
      <Sfx at={b(4)} name="rise" volume={0.45} />
    </AbsoluteFill>
  );
};
