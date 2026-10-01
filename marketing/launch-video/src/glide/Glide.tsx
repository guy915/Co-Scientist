import React from 'react';
import {AbsoluteFill, Sequence, useCurrentFrame} from 'remotion';
import '../shared/fonts';
import {Cursor} from '../shared/Cursor';
import {FloatCard} from '../shared/FloatCard';
import {Footnote} from '../shared/Footnote';
import {HeroFlask} from '../shared/HeroFlask';
import {Lockup} from '../shared/Lockup';
import {PromptBox} from '../shared/PromptBox';
import {TypeLine} from '../shared/TypeLine';
import {accel, emphasized, mix, ramp} from '../shared/motion';
import {C} from '../shared/tokens';
import {Agents, Ranked} from './Run';

export const GLIDE_FRAMES = 960;

const GOAL = 'What mechanisms drive antibiotic resistance in S. aureus biofilms?';

/** 0-110: the title line, then the real home screen rises into place. */
export const Arrive: React.FC = () => {
  const f = useCurrentFrame();
  const rise = ramp(f, 56, 46, emphasized);
  const push = ramp(f, 100, 40, emphasized);
  return (
    <AbsoluteFill>
      <HeroFlask size={760} y={mix(-30, -700, rise) + mix(60, 0, ramp(f, 0, 30, emphasized))} opacity={ramp(f, 0, 14) * (1 - ramp(f, 60, 30))} offset={40} />
      <AbsoluteFill style={{alignItems: 'center', paddingTop: 860}}>
        <TypeLine text="Introducing Open Co-Scientist" start={10} end={58} size={68} />
      </AbsoluteFill>
      <FloatCard
        src="ui/light-home.png"
        width={1500}
        y={mix(1000, 60, rise) + mix(0, -560, push)}
        x={mix(0, 420, push)}
        rx={mix(28, 0, rise)}
        scale={mix(0.86, 1, rise) * mix(1, 1.9, push)}
        glow={mix(1, 0, push)}
        opacity={1 - ramp(f, 114, 20, accel)}
        blur={ramp(f, 108, 22) * 18}
      />
    </AbsoluteFill>
  );
};

/** 110-230: the composer comes forward and the goal is typed and sent. */
export const Ask: React.FC = () => {
  const f = useCurrentFrame();
  const inn = ramp(f, 4, 22, emphasized);
  const out = ramp(f, 104, 16, accel);
  const cx = mix(1180, 1605, ramp(f, 70, 18, emphasized));
  const cy = mix(820, 615, ramp(f, 70, 18, emphasized));
  const press = ramp(f, 90, 4) * (1 - ramp(f, 94, 8));
  return (
    <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', opacity: inn * (1 - out)}}>
      <div style={{transform: `scale(${mix(0.92, 1.18, inn)}) translateY(${mix(0, -60, out)}px)`}}>
        <PromptBox text={GOAL} start={22} speed={1.4} send={92} width={1240} fontSize={42} />
      </div>
      <Cursor x={cx} y={cy} press={press} opacity={ramp(f, 66, 8) * (1 - ramp(f, 100, 8))} />
    </AbsoluteFill>
  );
};

/** 840-960: the end card. */
export const End: React.FC = () => <Lockup start={8} />;

/** Preview B: product-led, one continuous camera over the real app, Gemini-launch style. */
export const Glide: React.FC = () => (
  <AbsoluteFill style={{background: C.paper}}>
    <Sequence durationInFrames={140}><Arrive /></Sequence>
    <Sequence from={110} durationInFrames={125}><Ask /></Sequence>
    <Sequence from={225} durationInFrames={145}><Agents /></Sequence>
    <Sequence from={360} durationInFrames={490}><Ranked /></Sequence>
    <Sequence from={840}><End /></Sequence>
    <Sequence from={360} durationInFrames={480}><Footnote text="Screens from a demo run on ai-co-scientist.com. Sequences shortened." /></Sequence>
  </AbsoluteFill>
);
