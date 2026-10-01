import React from 'react';
import {AbsoluteFill, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {SEEDS} from '../data/demo_run';
import {Footnote} from '../shared/Footnote';
import {IdeaCard} from '../shared/IdeaCard';
import {Shape} from '../shared/Shape';
import {WordReveal} from '../shared/WordReveal';
import {accel, emphasized, envelope, mix, ramp} from '../shared/motion';
import {C, FONT} from '../shared/tokens';

const LEN = 75;
const VX = 1360;

/** One verb of the loop: the word on the left, the run's own ideas on the right. */
const Beat: React.FC<{word: string; line: string; children: React.ReactNode}> = ({word, line, children}) => {
  const f = useCurrentFrame();
  const sub = envelope(f, 8, LEN, 14, 10);
  return (
    <AbsoluteFill>
      <div style={{position: 'absolute', left: 140, top: 380, width: 760}}>
        <WordReveal text={word} start={0} end={LEN - 10} size={150} weight={500} align="left" />
        <div style={{fontFamily: FONT, fontSize: 54, color: C.inkSoft, marginTop: 20, lineHeight: 1.22, opacity: sub, transform: `translateY(${mix(16, 0, sub)}px)`}}>{line}</div>
      </div>
      {children}
      <Footnote text="Ideas from a demo run on ai-co-scientist.com." />
    </AbsoluteFill>
  );
};

const at = (x: number, y: number, extra = ''): React.CSSProperties => ({position: 'absolute', left: x, top: y, transform: `translate(-50%, -50%) ${extra}`});

export const Generate: React.FC = () => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const out = ramp(f, LEN - 12, 12, accel);
  return (
    <Beat word="Generate." line="Hypotheses drafted from the literature.">
      <div style={at(VX + 160, 300, `scale(${spring({frame: f, fps, config: {damping: 12}}) * (1 - out)})`)}>
        <Shape from="flower" to="cookie12" k={ramp(f, 10, 30)} size={380} fill={C.container.blue} fill2={C.deep.blue} rotate={f} />
      </div>
      {SEEDS.slice(0, 4).map((s, i) => {
        const t = spring({frame: f - 6 - i * 6, fps, config: {damping: 15, stiffness: 120}});
        return (
          <div key={s.title} style={{...at(VX + (i % 2 ? 40 : -40), 282 + i * 178, `translateY(${mix(120, 0, t)}px) rotate(${(i % 2 ? 1 : -1) * mix(6, 1.2, t)}deg)`), opacity: Math.min(1, t * 1.5) * (1 - out)}}>
            <IdeaCard tag={`Hypothesis ${i + 1}`} title={s.title} width={720} />
          </div>
        );
      })}
    </Beat>
  );
};

export const Debate: React.FC = () => {
  const f = useCurrentFrame();
  const meet = ramp(f, 4, 22, emphasized);
  const hit = ramp(f, 24, 6) * (1 - ramp(f, 30, 14));
  const ring = ramp(f, 24, 26);
  const win = ramp(f, 32, 14, emphasized);
  const out = ramp(f, LEN - 12, 12, accel);
  const card = (side: number, i: number, lead: boolean) => (
    <div style={{...at(VX + side * mix(700, 0, meet), 540 + side * 150 + side * 16 * hit, `rotate(${side * mix(14, 2.5, meet)}deg) scale(${lead ? mix(1, 1.05, win) : mix(1, 0.95, win)})`), opacity: (lead ? 1 : mix(1, 0.7, win)) * (1 - out)}}>
      <IdeaCard tag={lead ? `Elo ${SEEDS[i].elo}  ▲` : `Elo ${SEEDS[i].elo}`} title={SEEDS[i].title} width={700} lead={lead && win > 0.5} />
    </div>
  );
  return (
    <Beat word="Debate." line="Ideas argue head to head. Every result moves an Elo rating.">
      <div style={{...at(VX, 540, `scale(${mix(0.3, 1.5, ring)})`), width: 520, height: 520, borderRadius: '50%', border: `5px solid ${C.teal}`, opacity: (1 - ring) * 0.7 * (ring > 0 ? 1 : 0)}} />
      {card(1, 1, false)}
      {card(-1, 0, true)}
      <div style={{...at(VX, 540, `scale(${mix(0.4, 1, hit)})`), fontFamily: FONT, fontSize: 64, fontWeight: 700, color: C.teal, opacity: hit}}>vs</div>
    </Beat>
  );
};

export const Evolve: React.FC = () => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const out = ramp(f, LEN - 12, 12, accel);
  const parent = spring({frame: f, fps, config: {damping: 14}});
  const line = ramp(f, 16, 18, emphasized);
  const child = spring({frame: f - 26, fps, config: {damping: 12}});
  return (
    <Beat word="Evolve." line="The strongest ideas are refined into better ones.">
      <div style={at(VX + 300, 760, `scale(${child * (1 - out)}) rotate(${-f * 0.6}deg)`)}>
        <Shape from="clover" size={300} fill={C.container.green} fill2={C.deep.green} />
      </div>
      <svg width={1920} height={1080} style={{position: 'absolute', inset: 0, opacity: 1 - out}}>
        <line x1={VX} y1={420} x2={VX} y2={420 + 230 * line} stroke={C.teal} strokeWidth={6} strokeLinecap="round" strokeDasharray="2 14" />
      </svg>
      <div style={{...at(VX, 340, `translateY(${mix(-60, 0, parent)}px)`), opacity: parent * (1 - out)}}>
        <IdeaCard tag={`Generation 0 · Elo ${SEEDS[0].elo}`} title={SEEDS[0].title} width={720} />
      </div>
      <div style={{...at(VX, 740, `translateY(${mix(80, 0, child)}px) scale(${mix(0.9, 1, child)})`), opacity: Math.min(1, child * 1.4) * (1 - out)}}>
        <IdeaCard tag="Generation 1 · refined" title={`Refined: ${SEEDS[0].title}`} width={720} lead />
      </div>
    </Beat>
  );
};
