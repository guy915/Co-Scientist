import React from 'react';
import {AbsoluteFill, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {AGENTS} from '../data/agents';
import {Shape} from '../shared/Shape';
import {FloatCard} from '../shared/FloatCard';
import {ProofList} from '../shared/ProofList';
import {TypeLine} from '../shared/TypeLine';
import {type Pose, accel, envelope, mix, posed, ramp} from '../shared/motion';
import {C, FONT} from '../shared/tokens';

const STAGES = ['Planning the research', 'Generating hypotheses', 'Reviewing every idea', 'Running the tournament'];

/** Google's "Thinking…" pill, with four dots chasing in brand tones. */
export const StatusPill: React.FC<{label: string; f: number}> = ({label, f}) => (
  <div style={{display: 'inline-flex', alignItems: 'center', gap: 22, padding: '22px 36px', borderRadius: 999, background: '#fff', boxShadow: '0 0 0 1px rgba(31,31,31,0.08), 0 16px 40px rgba(31,31,31,0.10)', fontFamily: FONT, fontSize: 38, color: C.ink}}>
    <div style={{display: 'flex', gap: 8}}>
      {[C.teal, '#4C8DF6', '#34A853', '#F9AB00'].map((c, i) => (
        <div key={c} style={{width: 14, height: 14, borderRadius: 7, background: c, transform: `translateY(${Math.sin((f - i * 4) / 4) * 7}px)`}} />
      ))}
    </div>
    {label}
  </div>
);

/**
 * A caption line over a white band, so it stays legible over the UI below it.
 * Mounted only inside its own window: the band is opaque, so a band left on
 * screen buries the next caption's text. The text is positioned so it paints
 * above the (absolutely positioned) band.
 */
export const Caption: React.FC<{text: string; start: number; end: number}> = ({text, start, end}) => {
  const f = useCurrentFrame();
  if (f < start - 2 || f > end + 12) return null;
  return (
    <AbsoluteFill style={{alignItems: 'center'}}>
      <div style={{position: 'absolute', inset: '0 0 auto 0', height: 230, background: 'linear-gradient(#fff 74%, rgba(255,255,255,0))', opacity: envelope(f, start - 2, end + 12, 8, 10)}} />
      <TypeLine text={text} start={start} end={end} size={60} style={{marginTop: 84, position: 'relative'}} />
    </AbsoluteFill>
  );
};

/** 225-370: the run starts — the seven agents gather while the stage pill ticks on. */
export const Agents: React.FC = () => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const stage = Math.min(STAGES.length - 1, Math.floor(f / 32));
  const vis = envelope(f, 0, 140, 12, 12);
  return (
    <AbsoluteFill style={{opacity: vis}}>
      {AGENTS.map((a, i) => {
        const ang = (i / AGENTS.length) * Math.PI * 2 - Math.PI / 2 + f / 160;
        const s = spring({frame: f - i * 3, fps, config: {damping: 12}});
        return (
          <div key={a.name} style={{position: 'absolute', left: 960 + Math.cos(ang) * 560 - 90, top: 560 + Math.sin(ang) * 300 - 90, transform: `scale(${s})`}}>
            <Shape from={a.shape} size={180} fill={C.container[a.tone]} fill2={C.deep[a.tone]} rotate={f * 0.5} />
          </div>
        );
      })}
      <Caption text="A team of agents gets to work." start={6} end={136} />
      <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', paddingTop: 40}}>
        <div style={{transform: `translateY(${mix(30, 0, ramp(f, stage * 32, 10))}px) scale(1.3)`}}>
          <StatusPill label={STAGES[stage]} f={f} />
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// Keyframed camera. Frames are local to the scene. Each screen is framed on
// one region so a single thing is readable at a time; crops are fractions of
// the 1600x1000 captures.
const LEARN_CROP = {x: 0.22, y: 0.22, w: 0.62, h: 0.42};
const REPORT_CROP = {x: 0.215, y: 0.23, w: 0.61, h: 0.25};
// Flat, level screens that dissolve into each other: one readable thing per beat.
const LEARNING: Pose[] = [
  {f: 150, scale: 0.94, opacity: 0, glow: 0.8},
  {f: 178, scale: 1, opacity: 1},
  {f: 250},
  {f: 268, scale: 1.03, opacity: 0},
];
const REPORT: Pose[] = [
  {f: 262, scale: 0.94, opacity: 0, glow: 0.8},
  {f: 290, scale: 1, opacity: 1},
  {f: 470, scale: 1.05},
  {f: 490, opacity: 0},
];

/** One camera move: the ranked list, the evidence, the report, then all three together. */
const GLIDE_CAPTIONS = [
  'Every idea ranked in a head-to-head tournament.',
  'Every claim checked against the literature.',
  'Every run ends in a report you can act on.',
] as const;

export const Ranked: React.FC<{captions?: readonly string[]}> = ({captions = GLIDE_CAPTIONS}) => {
  const f = useCurrentFrame();
  const listOut = ramp(f, 140, 20, accel);
  return (
    <AbsoluteFill>
      {f < 165 && (
        <div style={{position: 'absolute', inset: 0, opacity: 1 - listOut, transform: `scale(${mix(1, 1.03, listOut)})`}}>
          <ProofList start={0} width={740} x={-130} y={44} chip="right" />
        </div>
      )}
      {f >= 145 && f < 272 && <FloatCard src="ui/light-learning.png" width={1640} crop={LEARN_CROP} {...posed(f, LEARNING)} />}
      {f >= 258 && <FloatCard src="ui/light-overview.png" width={1720} crop={REPORT_CROP} {...posed(f, REPORT)} />}
      <Caption text={captions[0]} start={10} end={140} />
      <Caption text={captions[1]} start={170} end={252} />
      <Caption text={captions[2]} start={280} end={470} />
    </AbsoluteFill>
  );
};
