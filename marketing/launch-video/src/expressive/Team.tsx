import React from 'react';
import {AbsoluteFill, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {Shape} from '../shared/Shape';
import {WordReveal} from '../shared/WordReveal';
import {accel, mix, ramp} from '../shared/motion';
import {C, FONT} from '../shared/tokens';
import {AGENTS} from '../data/agents';

/** 225-345: the question goes to seven agents, each a shape the landing page already uses. */
export const Team: React.FC = () => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const out = ramp(f, 106, 14, accel);
  return (
    <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center'}}>
      <div>
        <WordReveal text="Then hand it to a *team* of agents." start={0} end={106} size={92} />
      </div>
      <div style={{display: 'flex', gap: 26, marginTop: 110}}>
        {AGENTS.map((a, i) => {
          const s = spring({frame: f - 14 - i * 4, fps, config: {damping: 11, stiffness: 140}});
          const label = ramp(f, 26 + i * 4, 14);
          return (
            <div key={a.name} style={{display: 'flex', flexDirection: 'column', alignItems: 'center', width: 228, opacity: 1 - out, transform: `translateY(${out * -40}px)`}}>
              <div style={{transform: `scale(${s})`}}>
                <Shape from={a.shape} to="circle" k={0.5 + 0.5 * Math.sin((f + i * 9) / 14)} size={196} fill={C.container[a.tone]} fill2={C.deep[a.tone]} rotate={f * (i % 2 ? -0.6 : 0.6)} />
              </div>
              <div style={{fontFamily: FONT, fontSize: 42, fontWeight: 500, color: C.ink, marginTop: 24, whiteSpace: 'nowrap', opacity: label, transform: `translateY(${mix(12, 0, label)}px)`}}>
                {a.name}
              </div>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
