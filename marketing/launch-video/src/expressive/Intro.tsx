import React from 'react';
import {AbsoluteFill, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {HeroFlask} from '../shared/HeroFlask';
import {PromptBox} from '../shared/PromptBox';
import {Shape} from '../shared/Shape';
import {WordReveal} from '../shared/WordReveal';
import {accel, emphasized, envelope, mix, ramp} from '../shared/motion';
import {C} from '../shared/tokens';

/** 0-120: the glass flask lands on an Expressive shape, then makes room for the line. */
export const Opening: React.FC = () => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const pop = spring({frame: f, fps, config: {damping: 13, stiffness: 110}});
  const rise = ramp(f, 2, 26, emphasized);
  const shift = ramp(f, 42, 26, emphasized);
  const leave = ramp(f, 104, 16, accel);
  const gx = mix(0, -470, shift);
  const gs = mix(1, 0.74, shift) * (1 - leave * 0.3);
  return (
    <AbsoluteFill style={{opacity: 1 - leave}}>
      <div style={{position: 'absolute', inset: 0, transform: `translateX(${gx}px) scale(${gs})`}}>
        <div style={{position: 'absolute', left: 960 - 390, top: 540 - 390, transform: `scale(${pop})`}}>
          <Shape from="cookie12" to="flower" k={ramp(f, 30, 40)} size={780} fill={C.container.teal} fill2={C.deep.teal} rotate={f * 0.5} />
        </div>
        <HeroFlask size={900} y={mix(240, 10, rise)} opacity={ramp(f, 2, 14)} />
      </div>
      <div style={{position: 'absolute', left: 880, top: 400}}>
        <WordReveal text="Every breakthrough / starts with a *question.*" start={50} size={104} align="left" />
      </div>
    </AbsoluteFill>
  );
};

const GOAL = 'Which metabolic pathways could restore antibiotic susceptibility in S. aureus biofilms?';

/** 120-215: the product's own home question, then a goal typed into the composer. */
export const Ask: React.FC = () => {
  const f = useCurrentFrame();
  const box = ramp(f, 4, 20);
  const vis = envelope(f, 0, 95, 12, 12);
  return (
    <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', opacity: vis}}>
      <div style={{marginBottom: 60}}>
        <WordReveal text="What breakthrough should we make *today?*" start={0} size={76} weight={400} stagger={2} />
      </div>
      <div style={{opacity: box, transform: `translateY(${mix(40, 0, box)}px) scale(${mix(0.96, 1, box)})`}}>
        <PromptBox text={GOAL} start={16} speed={2.8} send={66} width={1440} fontSize={44} />
      </div>
    </AbsoluteFill>
  );
};
