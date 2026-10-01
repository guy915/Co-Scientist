import React from 'react';
import {AbsoluteFill, useCurrentFrame} from 'remotion';
import {AGENTS} from '../data/agents';
import {FloatCard} from '../shared/FloatCard';
import {Shape} from '../shared/Shape';
import {type Pose, posed} from '../shared/motion';
import {C} from '../shared/tokens';
import {useBeats} from './Beat';
import {Backdrop, LOOKS} from './Macro';
import {Sfx} from './Sfx';

// The app's left icon rail reads as a stray sliver once a screen is floated.
const NO_RAIL = {x: 0.03, y: 0, w: 0.97, h: 1};

/**
 * Three real screens fan out in depth around the home screen, then the camera
 * pushes into its "What breakthrough should we make today?" line, the
 * film's opening question asked back by the app.
 */
const Spread: React.FC<{f: number}> = ({f}) => {
  const b = useBeats();
  const push = b(3);
  const side = (dir: number, at: number): Pose[] => [
    {f: at, x: 0, ry: 0, scale: 0.7, opacity: 0},
    {f: at + 14, x: dir * 560, ry: dir * -26, scale: 0.66, opacity: 1, glow: 0.5},
    {f: push, x: dir * 600, scale: 0.68},
    {f: push + 16, x: dir * 1500, opacity: 0},
  ];
  const home: Pose[] = [
    {f: 0, y: 380, rx: 22, scale: 0.56, opacity: 0},
    {f: 16, y: 0, rx: 0, scale: 0.6, opacity: 1},
    {f: push, scale: 0.64},
    // The headline sits at (-0.1, -0.3) of the card; the card scales before it moves, so this centres it.
    {f: b(6) - 4, x: 2.3 * 0.1 * 1500, y: 2.3 * 0.3 * 966, scale: 2.3, glow: 0.2},
  ];
  return (
    <AbsoluteFill>
      <FloatCard src="ui/light-details.png" width={1100} crop={NO_RAIL} blur={2} {...posed(f, side(-1, b(0.5)))} />
      <FloatCard src="ui/light-overview.png" width={1100} crop={NO_RAIL} blur={2} {...posed(f, side(1, b(1)))} />
      <FloatCard src="ui/light-home.png" width={1500} crop={NO_RAIL} {...posed(f, home)} />
    </AbsoluteFill>
  );
};

/** The learning screen rises flat, then the camera drifts down its knowledge base. */
const Learning: React.FC<{f: number; len: number}> = ({f, len}) => {
  const keys: Pose[] = [
    {f: 0, y: 420, rx: 24, scale: 0.86, opacity: 0},
    {f: 14, y: 80, rx: 0, scale: 1, opacity: 1},
    {f: len, x: -1.4 * 0.12 * 1500, y: -1.4 * 0.24 * 966, scale: 1.4, glow: 0.3},
  ];
  return (
    <AbsoluteFill>
      <FloatCard src="ui/light-learning.png" width={1500} crop={NO_RAIL} fade {...posed(f, keys)} />
    </AbsoluteFill>
  );
};

const Agents: React.FC<{f: number}> = ({f}) => (
  <AbsoluteFill>
    {AGENTS.map((a, i) => {
      const ang = (i / AGENTS.length) * Math.PI * 2 + f / 30;
      return (
        <div key={a.name} style={{position: 'absolute', left: 960 + Math.cos(ang) * 420 - 130, top: 540 + Math.sin(ang) * 300 - 130}}>
          <Shape from={a.shape} size={260} fill={C.container[a.tone]} fill2={C.deep[a.tone]} rotate={f * 2} />
        </div>
      );
    })}
  </AbsoluteFill>
);

/**
 * Beats 65-76: three shots of the real app, each moving rather than cut on
 * every beat: the fanned-out screens, the agents, the knowledge base. The last
 * beat stutters through shapes into the breakdown.
 */
export const Montage: React.FC = () => {
  const f = useCurrentFrame();
  const b = useBeats();
  const cuts = [0, b(6), b(8)];
  const stutter = [0, 1, 2, 3].map(k => b(10 + k * 0.25));
  const all = [...cuts, ...stutter];
  const i = all.filter(c => f >= c).length - 1;
  const local = f - all[i];
  return (
    <AbsoluteFill style={{background: C.paper}}>
      {i >= cuts.length ? (
        <Backdrop look={LOOKS[(i - cuts.length + 3) % LOOKS.length]} f={local * 6 + i * 30} />
      ) : i === 0 ? (
        <Spread f={local} />
      ) : i === 1 ? (
        <Agents f={local} />
      ) : (
        <Learning f={local} len={b(10) - b(8)} />
      )}
      {/* Sound sits here, not in the shots: each shot's Sfx would count from the montage's start. */}
      {cuts.map(c => <Sfx key={c} at={c} name="shutter" volume={0.5} />)}
      <Sfx at={2} name="whoosh" volume={0.45} />
      <Sfx at={b(0.5)} name="pop1" volume={0.4} />
      <Sfx at={b(1)} name="pop2" volume={0.4} />
      <Sfx at={b(3)} name="swish" volume={0.45} />
      <Sfx at={b(8) + 4} name="whoosh" volume={0.4} />
      {stutter.map(c => <Sfx key={c} at={c} name="tick" volume={0.6} />)}
    </AbsoluteFill>
  );
};
