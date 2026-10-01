import React from 'react';
import {AbsoluteFill, useCurrentFrame} from 'remotion';
import {AGENTS} from '../data/agents';
import {IDEA_COUNT, MATCH_COUNT, SEEDS} from '../data/demo_run';
import {FloatCard} from '../shared/FloatCard';
import {Shape} from '../shared/Shape';
import {emphasized, mix, ramp} from '../shared/motion';
import {C, FONT} from '../shared/tokens';
import {useBeats} from './Beat';
import {Backdrop, LOOKS} from './Macro';
import {Sfx} from './Sfx';

type Crop = {x: number; y: number; w: number; h: number};
type Frame = {stat: number; label: string} | {ui: string; crop: Crop; width: number} | 'agents';

// The run in numbers, cut against the screens they come from. Every figure is
// the demo run's own: its overview reads 15 ideas over 27 minutes, a top Elo of
// 1386, 21 matches and 6 sources analyzed. Crops are fractions of the 1600x1000 captures.
const FRAMES: Frame[] = [
  {stat: IDEA_COUNT, label: 'ideas explored'},
  {ui: 'ui/light-ideas.png', crop: {x: 0.05, y: 0.2, w: 0.55, h: 0.38}, width: 1300},
  {stat: MATCH_COUNT, label: 'head-to-head matches'},
  {ui: 'ui/light-home.png', crop: {x: 0.79, y: 0.06, w: 0.2, h: 0.315}, width: 520},
  {stat: SEEDS[0].elo, label: 'top Elo rating'},
  {ui: 'ui/light-overview.png', crop: {x: 0.215, y: 0.475, w: 0.6, h: 0.37}, width: 1400},
  {stat: 27, label: 'minutes, start to finish'},
  {ui: 'ui/light-learning.png', crop: {x: 0.22, y: 0.22, w: 0.62, h: 0.42}, width: 1400},
  {stat: 6, label: 'sources analyzed'},
  'agents',
];

/** A figure counting up to its value as the frame lands. */
const Stat: React.FC<{value: number; label: string; f: number}> = ({value, label, f}) => {
  const t = ramp(f, 0, 12, emphasized);
  return (
    <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center', fontFamily: FONT, color: C.ink}}>
      <div style={{fontSize: 300, fontWeight: 500, letterSpacing: '-0.04em', lineHeight: 1, fontVariantNumeric: 'tabular-nums', transform: `scale(${mix(1.12, 1, t)})`}}>{Math.round(value * t)}</div>
      <div style={{fontSize: 60, marginTop: 20, background: 'rgba(255,255,255,0.86)', padding: '12px 36px', borderRadius: 999, opacity: ramp(f, 3, 8)}}>{label}</div>
    </AbsoluteFill>
  );
};

/** The seven agents circling their own count. */
const Agents: React.FC<{f: number}> = ({f}) => (
  <AbsoluteFill style={{background: C.paper}}>
    {AGENTS.map((a, i) => {
      const ang = (i / AGENTS.length) * Math.PI * 2 + f / 30;
      return (
        <div key={a.name} style={{position: 'absolute', left: 960 + Math.cos(ang) * 560 - 110, top: 540 + Math.sin(ang) * 340 - 110}}>
          <Shape from={a.shape} size={220} fill={C.container[a.tone]} fill2={C.deep[a.tone]} rotate={f * 2} />
        </div>
      );
    })}
    <Stat value={AGENTS.length} label="agents, one team" f={f} />
  </AbsoluteFill>
);

/**
 * Beats 65-76: a cut on every beat, a number then the screen it comes from,
 * each on its own full-bleed frame punching in; the last beat stutters
 * through shapes into the breakdown.
 */
export const Montage: React.FC = () => {
  const f = useCurrentFrame();
  const b = useBeats();
  const cuts = FRAMES.map((_, i) => b(i));
  const stutter = [0, 1, 2, 3].map(k => b(10 + k * 0.25));
  const all = [...cuts, ...stutter];
  const i = all.filter(c => f >= c).length - 1;
  const local = f - all[i];
  const frame = FRAMES[i];
  // Each frame's shapes travel the last quarter of their slide-in, a punch rather than an entrance.
  const enter = mix(0.75, 1, ramp(local, 0, 10, emphasized));
  return (
    <AbsoluteFill style={{background: C.paper}}>
      {i >= FRAMES.length ? (
        <Backdrop look={LOOKS[(i - FRAMES.length + 3) % LOOKS.length]} f={local * 6 + i * 30} />
      ) : frame === 'agents' ? (
        <Agents f={local} />
      ) : (
        <>
          <Backdrop look={LOOKS[i % LOOKS.length]} f={local + i * 40} enter={enter} />
          {'stat' in frame ? (
            <Stat value={frame.stat} label={frame.label} f={local} />
          ) : (
            <FloatCard src={frame.ui} width={frame.width} crop={frame.crop} scale={mix(1.1, 1, ramp(local, 0, 10, emphasized)) * (1 + local * 0.004)} ry={(i % 4 === 1 ? 1 : -1) * 5} glow={0.9} fade />
          )}
        </>
      )}
      {cuts.map(c => <Sfx key={c} at={c} name="shutter" volume={0.5} />)}
      {stutter.map(c => <Sfx key={c} at={c} name="tick" volume={0.6} />)}
    </AbsoluteFill>
  );
};
