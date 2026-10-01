import React from 'react';
import {AbsoluteFill, Sequence, useCurrentFrame} from 'remotion';
import '../shared/fonts';
import {Footnote} from '../shared/Footnote';
import {HeroFlask} from '../shared/HeroFlask';
import {Lockup} from '../shared/Lockup';
import {ProofList} from '../shared/ProofList';
import {WordReveal} from '../shared/WordReveal';
import {accel, emphasized, envelope, mix, ramp} from '../shared/motion';
import {FONT} from '../shared/tokens';
import {C} from '../shared/tokens';
import {Checked, Leaderboard} from './Board';
import {NETWORK_END, Network} from './Network';
import {Rings} from './Rings';

const OPEN = 100;
const BOARD_AT = OPEN + NETWORK_END - 10;
const PROOF_AT = BOARD_AT + 150;
const CHECK_AT = PROOF_AT + 100;
const END_AT = CHECK_AT + 130;
export const SIGNAL_FRAMES = END_AT + 150;

/** 0-100: the glass flask glows in the dark, then condenses to one point of light. */
const Spark: React.FC = () => {
  const f = useCurrentFrame();
  const shrink = ramp(f, 62, 30, accel);
  const dot = ramp(f, 80, 12);
  return (
    <AbsoluteFill>
      <div style={{position: 'absolute', left: 960 - 420, top: 500 - 420, width: 840, height: 840, borderRadius: '50%', background: 'radial-gradient(circle, rgba(94,200,190,0.35), rgba(94,200,190,0) 65%)', opacity: ramp(f, 0, 30) * (1 - shrink)}} />
      <HeroFlask size={820} y={-40 + mix(0, 0, shrink)} opacity={ramp(f, 0, 20) * (1 - shrink)} style={{transform: `scale(${mix(1, 0.05, shrink)})`, transformOrigin: '50% 68%'}} offset={80} />
      <div style={{position: 'absolute', left: 960 - 12, top: 490 - 12, width: 24, height: 24, borderRadius: 12, background: C.tealBright, boxShadow: '0 0 40px rgba(94,200,190,0.9)', transform: `scale(${dot})`}} />
      <div style={{position: 'absolute', left: 0, right: 0, bottom: 70}}>
        <WordReveal text="It starts with *one question.*" start={14} end={88} size={76} color="#F1F3F4" accentColor={C.tealBright} />
      </div>
    </AbsoluteFill>
  );
};

/** The same leaderboard, in the real app. */
const RealRun: React.FC = () => {
  const f = useCurrentFrame();
  const vis = envelope(f, 0, 100, 12, 12);
  const sub = ramp(f, 14, 16, emphasized);
  return (
    <AbsoluteFill style={{opacity: vis}}>
      <div style={{position: 'absolute', left: 150, top: 380, width: 820}}>
        <WordReveal text="Ranked, / in the *real* app." start={0} size={104} color="#F1F3F4" accentColor={C.tealBright} align="left" />
        <div style={{fontFamily: FONT, fontSize: 42, color: '#BDC1C6', marginTop: 26, opacity: sub}}>From a demo run on S. aureus biofilms.</div>
      </div>
      <ProofList start={4} width={780} x={420} dark />
    </AbsoluteFill>
  );
};

/** Preview C: abstract-led, dark, the tournament drawn as a living network with data callouts. */
export const Signal: React.FC = () => {
  return (
    <AbsoluteFill style={{background: C.night}}>
      <Rings />
      <Sequence durationInFrames={OPEN + 4}><Spark /></Sequence>
      <Sequence from={OPEN} durationInFrames={NETWORK_END}><Network /></Sequence>
      <Sequence from={BOARD_AT} durationInFrames={150}><Leaderboard /></Sequence>
      <Sequence from={PROOF_AT} durationInFrames={100}><RealRun /></Sequence>
      <Sequence from={CHECK_AT} durationInFrames={130}><Checked /></Sequence>
      <Sequence from={OPEN} durationInFrames={END_AT - OPEN}><Footnote text="Visualization of a demo run on ai-co-scientist.com. Sequences shortened." dark /></Sequence>
      <Sequence from={END_AT}><Lockup start={8} dark /></Sequence>
    </AbsoluteFill>
  );
};
