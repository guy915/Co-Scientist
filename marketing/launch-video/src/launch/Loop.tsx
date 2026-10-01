import React from 'react';
import {AbsoluteFill, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {SEEDS} from '../data/demo_run';
import {EloChart} from '../shared/EloChart';
import {IdeaCard} from '../shared/IdeaCard';
import {Shape} from '../shared/Shape';
import {emphasized, mix, ramp} from '../shared/motion';
import {C, FONT} from '../shared/tokens';
import {useBeats} from './Beat';
import {Sfx} from './Sfx';

const VX = 1360;

const at = (x: number, y: number, extra = ''): React.CSSProperties => ({position: 'absolute', left: x, top: y, transform: `translate(-50%, -50%) ${extra}`});

/**
 * One verb of the loop, one bar each, hard-cut on the downbeat: the word holds
 * its place on the left while the right side changes, the trailer's word-swap.
 */
const Verb: React.FC<{word: string; line: string; children: React.ReactNode}> = ({word, line, children}) => {
  const f = useCurrentFrame();
  const sub = ramp(f, 6, 12);
  return (
    <AbsoluteFill>
      <div style={{position: 'absolute', left: 140, top: 390, width: 760}}>
        <div style={{fontFamily: FONT, fontSize: 168, fontWeight: 500, letterSpacing: '-0.035em', color: C.ink, transform: `scale(${mix(1.05, 1, ramp(f, 0, 8))})`, transformOrigin: 'left center'}}>{word}</div>
        <div style={{fontFamily: FONT, fontSize: 52, color: C.inkSoft, marginTop: 18, lineHeight: 1.22, opacity: sub, transform: `translateY(${mix(14, 0, sub)}px)`}}>{line}</div>
      </div>
      {children}
      <Sfx at={0} name="swish" volume={0.4} />
    </AbsoluteFill>
  );
};

/** Beats 25-29: four of the run's real seed ideas land on eighth notes. */
export const Generate: React.FC = () => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const b = useBeats();
  const lands = [0, 1, 2, 3].map(i => b(0.5 + i * 0.5));
  return (
    <Verb word="Generate." line="Hypotheses drafted from the literature.">
      <div style={at(VX + 180, 300, `scale(${spring({frame: f, fps, config: {damping: 12}})})`)}>
        <Shape from="flower" to="cookie12" k={ramp(f, 10, 30)} size={380} fill={C.container.blue} fill2={C.deep.blue} rotate={f} />
      </div>
      {SEEDS.slice(0, 4).map((s, i) => {
        const t = spring({frame: f - lands[i] + 4, fps, config: {damping: 15, stiffness: 150}});
        return (
          <div key={s.title} style={{...at(VX + (i % 2 ? 40 : -40), 282 + i * 178, `translateY(${mix(140, 0, t)}px) rotate(${(i % 2 ? 1 : -1) * mix(7, 1.2, t)}deg)`), opacity: Math.min(1, t * 1.6)}}>
            <IdeaCard tag={`Hypothesis ${i + 1}`} title={s.title} width={720} />
          </div>
        );
      })}
      {lands.map((l, i) => <Sfx key={l} at={l} name={`pop${i + 1}`} volume={0.4} />)}
    </Verb>
  );
};

/** Beats 29-33: two ideas collide on beat 1, the winner takes the rating on beat 2. */
export const Debate: React.FC = () => {
  const f = useCurrentFrame();
  const b = useBeats();
  const hitAt = b(1);
  const winAt = b(2);
  const meet = ramp(f, 0, hitAt, emphasized);
  const hit = ramp(f, hitAt, 4) * (1 - ramp(f, hitAt + 4, 14));
  const ring = ramp(f, hitAt, 26);
  const win = ramp(f, winAt, 12, emphasized);
  const card = (side: number, i: number, lead: boolean) => (
    <div style={{...at(VX + side * mix(760, 0, meet), 540 + side * 150 + side * 18 * hit, `rotate(${side * mix(14, 2.5, meet)}deg) scale(${lead ? mix(1, 1.06, win) : mix(1, 0.94, win)})`), opacity: lead ? 1 : mix(1, 0.6, win)}}>
      <IdeaCard tag={lead ? `Elo ${SEEDS[i].elo}  ▲` : `Elo ${SEEDS[i].elo}`} title={SEEDS[i].title} width={700} lead={lead && win > 0.5} />
    </div>
  );
  return (
    <Verb word="Debate." line="Ideas argue head to head. Every result moves an Elo rating.">
      <div style={{...at(VX, 540, `scale(${mix(0.3, 1.6, ring)})`), width: 520, height: 520, borderRadius: '50%', border: `5px solid ${C.teal}`, opacity: (1 - ring) * 0.7 * (f >= hitAt ? 1 : 0)}} />
      {card(1, 1, false)}
      {card(-1, 0, true)}
      <div style={{...at(VX, 540, `scale(${mix(0.4, 1, hit)})`), fontFamily: FONT, fontSize: 64, fontWeight: 700, color: C.teal, opacity: hit}}>vs</div>
      <Sfx at={hitAt - 9} name="whoosh" volume={0.35} />
      <Sfx at={hitAt} name="clack" volume={0.65} />
      <Sfx at={winAt} name="ding" volume={0.45} />
    </Verb>
  );
};

/** Beats 33-37: the leader is refined; its child lands on beat 1. */
export const Evolve: React.FC = () => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const b = useBeats();
  const childAt = b(1);
  const parent = spring({frame: f, fps, config: {damping: 14}});
  const line = ramp(f, 4, childAt - 4, emphasized);
  const child = spring({frame: f - childAt, fps, config: {damping: 12, stiffness: 150}});
  return (
    <Verb word="Evolve." line="The strongest ideas are refined into better ones.">
      <div style={at(VX + 300, 760, `scale(${child}) rotate(${-f * 0.6}deg)`)}>
        <Shape from="clover" size={300} fill={C.container.green} fill2={C.deep.green} />
      </div>
      <svg width={1920} height={1080} style={{position: 'absolute', inset: 0}}>
        <line x1={VX} y1={420} x2={VX} y2={420 + 230 * line} stroke={C.teal} strokeWidth={6} strokeLinecap="round" strokeDasharray="2 14" />
      </svg>
      <div style={{...at(VX, 340, `translateY(${mix(-60, 0, parent)}px)`), opacity: parent}}>
        <IdeaCard tag={`Generation 0 · Elo ${SEEDS[0].elo}`} title={SEEDS[0].title} width={720} />
      </div>
      <div style={{...at(VX, 740, `translateY(${mix(80, 0, child)}px) scale(${mix(0.9, 1, child)})`), opacity: Math.min(1, child * 1.4)}}>
        <IdeaCard tag="Generation 1 · refined" title={`Refined: ${SEEDS[0].title}`} width={720} lead />
      </div>
      <Sfx at={childAt} name="pop5" volume={0.5} />
      <Sfx at={childAt + 2} name="sparkle" volume={0.3} />
    </Verb>
  );
};

/** Beats 37-41: the tournament draws itself; the leader's line tops out on beat 3. */
export const Rank: React.FC = () => {
  const b = useBeats();
  const done = b(3);
  return (
    <Verb word="Rank." line="A tournament decides which ideas lead.">
      <div style={{position: 'absolute', left: 1000, top: 300}}>
        <EloChart start={2} dur={done - 2} width={700} height={460} />
      </div>
      {[0, 1, 2].map(k => <Sfx key={k} at={b(k) + 1} name={`blip${k * 2}`} volume={0.35} />)}
      <Sfx at={done} name="ding-hi" volume={0.45} />
    </Verb>
  );
};
