import React from 'react';
import {AbsoluteFill, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {SEEDS} from '../data/demo_run';
import {EloChart} from '../shared/EloChart';
import {IdeaCard} from '../shared/IdeaCard';
import {Shape} from '../shared/Shape';
import {emphasized, mix, ramp} from '../shared/motion';
import {C, FONT} from '../shared/tokens';
import {useBeats} from './Beat';
import {WordFrame} from './Macro';
import {Sfx} from './Sfx';

// The loop runs as the trailer's alternation: a verb over a full-bleed frame,
// then two beats of what it does, each cut hard on the beat.

/** A verb's title shot: the word on its own frame, with its one-line gloss. */
export const VerbShot: React.FC<{word: string; gloss: string; look: number}> = ({word, gloss, look}) => (
  <AbsoluteFill>
    <WordFrame word={word} chip={gloss} look={look} />
    <Sfx at={0} name="shutter" volume={0.55} />
    <Sfx at={6} name="swish" volume={0.35} />
  </AbsoluteFill>
);

const at = (x: number, y: number, extra = ''): React.CSSProperties => ({position: 'absolute', left: x, top: y, transform: `translate(-50%, -50%) ${extra}`});

/** Four of the run's real seed ideas land on eighth notes, two by two. */
export const Cards: React.FC = () => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const b = useBeats();
  const lands = [0, 0.5, 1, 1.5].map(k => b(k));
  return (
    <AbsoluteFill>
      {SEEDS.slice(0, 4).map((s, i) => {
        const t = spring({frame: f - lands[i] + 3, fps, config: {damping: 15, stiffness: 170}});
        const x = 960 + (i % 2 ? 410 : -410);
        const y = 540 + (i < 2 ? -130 : 130);
        return (
          <div key={s.title} style={{...at(x, y, `translateY(${mix(160, 0, t)}px) rotate(${(i % 2 ? 1 : -1) * mix(8, 1, t)}deg) scale(${1 + f * 0.0015})`), opacity: Math.min(1, t * 1.6)}}>
            <IdeaCard tag={`Hypothesis ${i + 1}`} title={s.title} width={760} />
          </div>
        );
      })}
      {lands.map((l, i) => <Sfx key={l} at={l} name={`pop${i + 1}`} volume={0.4} />)}
    </AbsoluteFill>
  );
};

/** Two ideas slide in and collide on beat 1; the winner takes the rating half a beat later. */
export const Clash: React.FC = () => {
  const f = useCurrentFrame();
  const b = useBeats();
  const hitAt = b(1);
  const winAt = b(1.5);
  const meet = ramp(f, 0, hitAt, emphasized);
  const hit = ramp(f, hitAt, 3) * (1 - ramp(f, hitAt + 3, 12));
  const ring = ramp(f, hitAt, 22);
  const win = ramp(f, winAt, 10, emphasized);
  const card = (side: number, i: number, lead: boolean) => (
    <div style={{...at(960 + side * mix(900, 330, meet), 540 + side * 20 * hit, `rotate(${side * mix(10, 2, meet)}deg) scale(${lead ? mix(1, 1.08, win) : mix(1, 0.92, win)})`), opacity: lead ? 1 : mix(1, 0.55, win)}}>
      <IdeaCard tag={lead ? `Elo ${SEEDS[i].elo}  ▲` : `Elo ${SEEDS[i].elo}`} title={SEEDS[i].title} width={600} lead={lead && win > 0.5} />
    </div>
  );
  return (
    <AbsoluteFill>
      <div style={{...at(960, 540, `scale(${mix(0.3, 2, ring)})`), width: 520, height: 520, borderRadius: '50%', border: `6px solid ${C.teal}`, opacity: (1 - ring) * 0.7 * (f >= hitAt ? 1 : 0)}} />
      {card(1, 1, false)}
      {card(-1, 0, true)}
      <div style={{...at(960, 540, `scale(${mix(0.4, 1.2, hit)})`), fontFamily: FONT, fontSize: 84, fontWeight: 700, color: C.teal, opacity: hit}}>vs</div>
      <Sfx at={0} name="shutter" volume={0.5} />
      <Sfx at={hitAt - 2} name="whoosh" volume={0.35} />
      <Sfx at={hitAt} name="clack" volume={0.65} />
      <Sfx at={winAt} name="ding" volume={0.45} />
    </AbsoluteFill>
  );
};

/** The leader is refined; its child lands on beat 1. */
export const Child: React.FC = () => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const b = useBeats();
  const childAt = b(1);
  const line = ramp(f, 2, childAt - 2, emphasized);
  const child = spring({frame: f - childAt, fps, config: {damping: 12, stiffness: 160}});
  return (
    <AbsoluteFill>
      <div style={at(1320, 760, `scale(${child}) rotate(${-f * 0.8}deg)`)}>
        <Shape from="clover" size={320} fill={C.container.green} fill2={C.deep.green} />
      </div>
      <svg width={1920} height={1080} style={{position: 'absolute', inset: 0}}>
        <line x1={960} y1={420} x2={960} y2={420 + 210 * line} stroke={C.teal} strokeWidth={6} strokeLinecap="round" strokeDasharray="2 14" />
      </svg>
      <div style={at(960, 330)}>
        <IdeaCard tag={`Generation 0 · Elo ${SEEDS[0].elo}`} title={SEEDS[0].title} width={820} />
      </div>
      <div style={{...at(960, 740, `translateY(${mix(90, 0, child)}px) scale(${mix(0.88, 1, child)})`), opacity: Math.min(1, child * 1.4)}}>
        <IdeaCard tag="Generation 1 · refined" title={`Refined: ${SEEDS[0].title}`} width={820} lead />
      </div>
      <Sfx at={0} name="shutter" volume={0.5} />
      <Sfx at={childAt} name="pop5" volume={0.5} />
      <Sfx at={childAt + 2} name="sparkle" volume={0.3} />
    </AbsoluteFill>
  );
};

/** The tournament draws itself; the leader's line tops out at 1386 on beat 1.5. */
export const Chart: React.FC = () => {
  const b = useBeats();
  const done = b(1.5);
  return (
    <AbsoluteFill>
      <div style={{position: 'absolute', left: 260, top: 200}}>
        <EloChart start={0} dur={done} width={1300} height={640} />
      </div>
      {[0, 0.5, 1].map((k, i) => <Sfx key={k} at={b(k) + 1} name={`blip${i * 2}`} volume={0.35} />)}
      <Sfx at={done} name="ding-hi" volume={0.45} />
    </AbsoluteFill>
  );
};
