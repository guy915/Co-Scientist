import React from 'react';
import {AbsoluteFill, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {AGENTS} from '../data/agents';
import {StatusPill} from '../glide/Run';
import {Shape, type ShapeName} from '../shared/Shape';
import {WordReveal} from '../shared/WordReveal';
import {emphasized, mix, ramp} from '../shared/motion';
import {C, FONT} from '../shared/tokens';
import {useBeats} from './Beat';
import {Sfx} from './Sfx';

const SHAPES = AGENTS.map(a => a.shape);

/** The shape agent `i` wears after `n` stutter steps: each steps onto its neighbour's. */
const worn = (i: number, n: number): ShapeName => SHAPES[(i + n) % SHAPES.length];

/**
 * Beats 15-21: the seven agents pop in on eighth notes, a rising pentatonic
 * run under them, then stutter through each other's shapes into the downbeat.
 */
export const Team: React.FC = () => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const b = useBeats();
  const pops = AGENTS.map((_, i) => b(1 + i * 0.5));
  const stutter = [0, 1, 2, 3].map(k => b(5) + k * 5);
  const n = stutter.filter(s => f >= s).length;
  const morph = n ? ramp(f, stutter[n - 1], 3) : 0;
  return (
    <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center'}}>
      <WordReveal text="Hand it to a *team* of agents." start={0} size={96} stagger={2} />
      <div style={{display: 'flex', gap: 26, marginTop: 110}}>
        {AGENTS.map((a, i) => {
          const s = spring({frame: f - pops[i], fps, config: {damping: 10, stiffness: 170}});
          const label = ramp(f, pops[i] + 4, 10);
          return (
            <div key={a.name} style={{display: 'flex', flexDirection: 'column', alignItems: 'center', width: 228}}>
              <div style={{transform: `scale(${s * (1 + 0.08 * (1 - morph) * (n ? 1 : 0))})`}}>
                <Shape from={worn(i, Math.max(0, n - 1))} to={worn(i, n)} k={n ? morph : 0} size={196} fill={C.container[a.tone]} fill2={C.deep[a.tone]} rotate={f * (i % 2 ? -0.7 : 0.7)} />
              </div>
              <div style={{fontFamily: FONT, fontSize: 42, fontWeight: 500, color: C.ink, marginTop: 24, whiteSpace: 'nowrap', opacity: label, transform: `translateY(${mix(12, 0, label)}px)`}}>
                {a.name}
              </div>
            </div>
          );
        })}
      </div>
      {pops.map((p, i) => <Sfx key={p} at={p} name={`pop${i}`} volume={0.4} />)}
      {stutter.map(s => <Sfx key={s} at={s} name="morph" volume={0.4} />)}
    </AbsoluteFill>
  );
};

const STAGES = ['Planning the research', 'Generating hypotheses', 'Reviewing every idea', 'Running the tournament'];

/** Beats 21-25: the agents orbit while the run's stage ticks over on every beat. */
export const Working: React.FC = () => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const b = useBeats();
  const at = STAGES.map((_, k) => b(k));
  const stage = at.filter(s => f >= s).length - 1;
  const swap = ramp(f, at[stage], 8, emphasized);
  return (
    <AbsoluteFill>
      {AGENTS.map((a, i) => {
        const ang = (i / AGENTS.length) * Math.PI * 2 - Math.PI / 2 + f / 70;
        const s = spring({frame: f - i, fps, config: {damping: 12, stiffness: 150}});
        return (
          <div key={a.name} style={{position: 'absolute', left: 960 + Math.cos(ang) * 600 - 95, top: 540 + Math.sin(ang) * 330 - 95, transform: `scale(${s})`}}>
            <Shape from={a.shape} size={190} fill={C.container[a.tone]} fill2={C.deep[a.tone]} rotate={f * 0.9} />
          </div>
        );
      })}
      <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center'}}>
        <div style={{transform: `translateY(${mix(24, 0, swap)}px) scale(1.4)`, opacity: mix(0.3, 1, swap)}}>
          <StatusPill label={STAGES[stage]} f={f} />
        </div>
      </AbsoluteFill>
      {at.map((s, k) => <Sfx key={s} at={s} name={k ? 'tick' : 'whoosh'} volume={k ? 0.6 : 0.4} />)}
    </AbsoluteFill>
  );
};
