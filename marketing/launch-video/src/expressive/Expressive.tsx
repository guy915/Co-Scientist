import React from 'react';
import {AbsoluteFill, Sequence, useCurrentFrame} from 'remotion';
import '../shared/fonts';
import {Lockup} from '../shared/Lockup';
import {Shape} from '../shared/Shape';
import {ramp} from '../shared/motion';
import {C} from '../shared/tokens';
import {AGENTS} from '../data/agents';
import {Ask, Opening} from './Intro';
import {Debate, Evolve, Generate} from './Loop';
import {Evidence, Rank, RealRun} from './Proof';
import {Team} from './Team';

export const EXPRESSIVE_FRAMES = 990;

/** The agents' shapes settle into a quiet orbit around the end card. */
const Orbit: React.FC = () => {
  const f = useCurrentFrame();
  return (
    <AbsoluteFill>
      {AGENTS.map((a, i) => {
        const t = ramp(f, i * 3, 30);
        const ang = (i / AGENTS.length) * Math.PI * 2 + f / 220;
        return (
          <div key={a.name} style={{position: 'absolute', left: 960 + Math.cos(ang) * 780 - 60, top: 540 + Math.sin(ang) * 400 - 60, opacity: t * 0.9}}>
            <Shape from={a.shape} size={130} fill={C.container[a.tone]} fill2={C.deep[a.tone]} rotate={f * 0.5} />
          </div>
        );
      })}
    </AbsoluteFill>
  );
};

/** Preview A: type-led, Material 3 Expressive shapes, kinetic 2-3 s beats on white. */
export const Expressive: React.FC = () => (
  <AbsoluteFill style={{background: C.paper}}>
    <Sequence durationInFrames={120}><Opening /></Sequence>
    <Sequence from={120} durationInFrames={95}><Ask /></Sequence>
    <Sequence from={215} durationInFrames={120}><Team /></Sequence>
    <Sequence from={335} durationInFrames={75}><Generate /></Sequence>
    <Sequence from={410} durationInFrames={75}><Debate /></Sequence>
    <Sequence from={485} durationInFrames={75}><Evolve /></Sequence>
    <Sequence from={560} durationInFrames={120}><Rank /></Sequence>
    <Sequence from={680} durationInFrames={100}><RealRun /></Sequence>
    <Sequence from={780} durationInFrames={95}><Evidence /></Sequence>
    <Sequence from={870}>
      <Orbit />
      <Lockup start={10} />
    </Sequence>
  </AbsoluteFill>
);
