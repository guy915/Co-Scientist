import React from 'react';
import {AbsoluteFill, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {SEEDS} from '../data/demo_run';
import {EloChart} from '../shared/EloChart';
import {IdeaCard} from '../shared/IdeaCard';
import {emphasized, mix, ramp} from '../shared/motion';
import {C, FONT} from '../shared/tokens';
import {useBeats} from './Beat';
import {Backdrop, LOOKS, WordFrame} from './Macro';
import {Sfx} from './Sfx';

// The loop runs as the trailer's alternation: a verb over a full-bleed frame,
// then two beats of what it does on that same frame, the foreground cut hard
// on the beat while the shapes behind carry straight through.

/** A verb's title shot: the word on its own frame, with its one-line gloss. */
export const VerbShot: React.FC<{word: string; gloss: string; look: number}> = ({word, gloss, look}) => (
  <AbsoluteFill>
    <WordFrame word={word} chip={gloss} look={look} />
    <Sfx at={0} name="shutter" volume={0.55} />
    <Sfx at={6} name="swish" volume={0.35} />
  </AbsoluteFill>
);

const at = (x: number, y: number, extra = ''): React.CSSProperties => ({position: 'absolute', left: x, top: y, transform: `translate(-50%, -50%) ${extra}`});

/**
 * A demo shot continues its verb's frame: the scene before it is two beats
 * long, so the shapes pick up exactly where the verb shot left them.
 */
const OnFrame: React.FC<{look: number; children: React.ReactNode}> = ({look, children}) => {
  const f = useCurrentFrame();
  const b = useBeats();
  return (
    <AbsoluteFill>
      <Backdrop look={LOOKS[look % LOOKS.length]} f={f - b(-2)} />
      {children}
    </AbsoluteFill>
  );
};

/** Four of the run's real seed ideas fly out of the frame's big shape, landing on eighth notes. */
export const Cards: React.FC<{look: number}> = ({look}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const b = useBeats();
  const lands = [0, 0.5, 1, 1.5].map(k => b(k));
  const src = LOOKS[look % LOOKS.length];
  return (
    <OnFrame look={look}>
      {SEEDS.slice(0, 4).map((s, i) => {
        const t = spring({frame: f - lands[i] + 4, fps, config: {damping: 15, stiffness: 160}});
        const x = mix(src.x, 960 + (i % 2 ? 420 : -420), t);
        const y = mix(src.y, 540 + (i < 2 ? -150 : 150), t);
        return (
          <div key={s.title} style={{...at(x, y, `rotate(${(i % 2 ? 1 : -1) * mix(24, 1.5, t)}deg) scale(${mix(0.3, 1, t) * (1 + f * 0.0012)})`), opacity: Math.min(1, t * 2)}}>
            <IdeaCard tag={`Hypothesis ${i + 1}`} title={s.title} width={800} />
          </div>
        );
      })}
      {lands.map((l, i) => <Sfx key={l} at={l} name={`pop${i + 1}`} volume={0.4} />)}
    </OnFrame>
  );
};

/** Two ideas slide in and collide on beat 1; the winner takes the rating half a beat later. */
export const Clash: React.FC<{look: number}> = ({look}) => {
  const f = useCurrentFrame();
  const b = useBeats();
  const hitAt = b(1);
  const winAt = b(1.5);
  const meet = ramp(f, 0, hitAt, emphasized);
  const hit = ramp(f, hitAt, 3) * (1 - ramp(f, hitAt + 3, 12));
  const ring = ramp(f, hitAt, 22);
  const win = ramp(f, winAt, 10, emphasized);
  const card = (side: number, i: number, lead: boolean) => (
    <div style={{...at(960 + side * mix(1000, 370, meet), 540 + side * 24 * hit, `rotate(${side * mix(12, 2, meet)}deg) scale(${lead ? mix(1.15, 1.25, win) : mix(1.15, 1, win)})`), opacity: lead ? 1 : mix(1, 0.6, win)}}>
      <IdeaCard tag={lead ? `Elo ${SEEDS[i].elo}  ▲` : `Elo ${SEEDS[i].elo}`} title={SEEDS[i].title} width={600} lead={lead && win > 0.5} />
    </div>
  );
  return (
    <OnFrame look={look}>
      <div style={{...at(960, 540, `scale(${mix(0.3, 2.4, ring)})`), width: 520, height: 520, borderRadius: '50%', border: '8px solid #fff', opacity: (1 - ring) * 0.9 * (f >= hitAt ? 1 : 0)}} />
      {card(1, 1, false)}
      {card(-1, 0, true)}
      <div style={{...at(960, 540, `scale(${mix(0.4, 1.15, hit)})`), width: 170, height: 170, borderRadius: '50%', background: '#fff', boxShadow: '0 18px 44px rgba(31,31,31,0.16)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: FONT, fontSize: 76, fontWeight: 700, color: C.ink, opacity: hit}}>vs</div>
      <Sfx at={0} name="shutter" volume={0.5} />
      <Sfx at={hitAt - 2} name="whoosh" volume={0.35} />
      <Sfx at={hitAt} name="clack" volume={0.65} />
      <Sfx at={winAt} name="ding" volume={0.45} />
    </OnFrame>
  );
};

/** The leader is refined; its child drops out of it on beat 1. */
export const Child: React.FC<{look: number}> = ({look}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const b = useBeats();
  const childAt = b(1);
  const line = ramp(f, 2, childAt - 2, emphasized);
  const child = spring({frame: f - childAt, fps, config: {damping: 12, stiffness: 160}});
  const push = 1 + f * 0.0012;
  return (
    <OnFrame look={look}>
      <AbsoluteFill style={{transform: `scale(${push})`}}>
        <svg width={1920} height={1080} style={{position: 'absolute', inset: 0}}>
          <line x1={960} y1={430} x2={960} y2={430 + 220 * line} stroke={C.ink} strokeOpacity={0.55} strokeWidth={7} strokeLinecap="round" strokeDasharray="2 16" />
        </svg>
        <div style={at(960, 320, 'scale(1.15)')}>
          <IdeaCard tag={`Generation 0 · Elo ${SEEDS[0].elo}`} title={SEEDS[0].title} width={820} />
        </div>
        <div style={{...at(960, 300 + 470 * child, `rotate(${mix(-6, 0, child)}deg) scale(${mix(0.7, 1.15, child)})`), opacity: Math.min(1, child * 1.6)}}>
          <IdeaCard tag="Generation 1 · refined" title={`Refined: ${SEEDS[0].title}`} width={820} lead />
        </div>
      </AbsoluteFill>
      <Sfx at={0} name="shutter" volume={0.5} />
      <Sfx at={childAt} name="pop5" volume={0.5} />
      <Sfx at={childAt + 2} name="sparkle" volume={0.3} />
    </OnFrame>
  );
};

/** The tournament draws itself on a white panel; the leader's line tops out at 1386 on beat 1.5. */
export const Chart: React.FC<{look: number}> = ({look}) => {
  const f = useCurrentFrame();
  const b = useBeats();
  const done = b(1.5);
  const inn = ramp(f, 0, 10, emphasized);
  return (
    <OnFrame look={look}>
      <div style={{position: 'absolute', left: 120, top: 150, width: 1680, height: 800, borderRadius: 44, background: '#fff', boxShadow: '0 0 0 2px rgba(31,31,31,0.05), 0 40px 90px rgba(31,31,31,0.14)', transform: `translateY(${mix(80, 0, inn)}px) scale(${mix(0.94, 1, inn) * (1 + f * 0.001)})`}}>
        <div style={{position: 'absolute', left: 170, top: 80}}>
          <EloChart start={0} dur={done} width={1300} height={640} />
        </div>
      </div>
      {[0, 0.5, 1].map((k, i) => <Sfx key={k} at={b(k) + 1} name={`blip${i * 2}`} volume={0.35} />)}
      <Sfx at={done} name="ding-hi" volume={0.45} />
    </OnFrame>
  );
};
