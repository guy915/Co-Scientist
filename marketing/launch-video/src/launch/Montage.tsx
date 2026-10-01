import React from 'react';
import {AbsoluteFill, useCurrentFrame} from 'remotion';
import {AGENTS} from '../data/agents';
import {FloatCard} from '../shared/FloatCard';
import {Footnote} from '../shared/Footnote';
import {Shape} from '../shared/Shape';
import {C} from '../shared/tokens';
import {useBeats} from './Beat';
import {Backdrop, LOOKS} from './Macro';
import {Sfx} from './Sfx';

type Crop = {x: number; y: number; w: number; h: number};
// `fade` marks crops that end inside running text.
type Shot = {ui: string; crop: Crop; width: number; fade?: boolean} | 'agents';

// Real screens from the demo run, each region shown once and none the film
// has already shown (home, run specification, idea detail, other runs,
// insights, lower-ranked ideas), alternating themes, each framed on the one
// region that reads at a glance. Crops are fractions of the 1600x1000 captures.
const SHOTS: Shot[] = [
  {ui: 'ui/light-home.png', crop: {x: 0.1, y: 0.1, w: 0.6, h: 0.42}, width: 1500},
  {ui: 'ui/dark-details.png', crop: {x: 0.215, y: 0.22, w: 0.62, h: 0.4}, width: 1500, fade: true},
  {ui: 'ui/light-home.png', crop: {x: 0.79, y: 0.06, w: 0.2, h: 0.315}, width: 560, fade: true},
  'agents',
  {ui: 'ui/light-ideas.png', crop: {x: 0.33, y: 0.215, w: 0.49, h: 0.4}, width: 1440, fade: true},
  {ui: 'ui/dark-home.png', crop: {x: 0.79, y: 0.52, w: 0.2, h: 0.3}, width: 560, fade: true},
  {ui: 'ui/light-overview.png', crop: {x: 0.215, y: 0.475, w: 0.6, h: 0.37}, width: 1500, fade: true},
  {ui: 'ui/dark-ideas.png', crop: {x: 0.045, y: 0.675, w: 0.265, h: 0.135}, width: 900, fade: true},
  {ui: 'ui/light-details.png', crop: {x: 0.215, y: 0.65, w: 0.62, h: 0.15}, width: 1600, fade: true},
  {ui: 'ui/dark-learning.png', crop: {x: 0.22, y: 0.72, w: 0.62, h: 0.27}, width: 1500, fade: true},
];

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
 * Beats 65-76: a cut on every beat through the real app, each shot pushing in,
 * then the last beat stutters through shapes into the breakdown. Only the
 * screen shots carry the screens footnote.
 */
export const Montage: React.FC = () => {
  const f = useCurrentFrame();
  const b = useBeats();
  const cuts = SHOTS.map((_, i) => b(i));
  const stutter = [0, 1, 2, 3].map(k => b(10 + k * 0.25));
  const all = [...cuts, ...stutter];
  const i = all.filter(c => f >= c).length - 1;
  const local = f - all[i];
  const shot = SHOTS[i];
  return (
    <AbsoluteFill style={{background: C.paper}}>
      {i >= SHOTS.length ? (
        <Backdrop look={LOOKS[(i - SHOTS.length + 3) % LOOKS.length]} f={local * 6 + i * 30} />
      ) : shot === 'agents' ? (
        <Agents f={local} />
      ) : (
        <>
          <FloatCard src={shot.ui} width={shot.width} crop={shot.crop} dark={shot.ui.includes('dark')} scale={1 + local * 0.006} ry={(i % 2 ? -1 : 1) * (4 - local * 0.3)} glow={0.9} fade={shot.fade} />
          <Footnote text="Screens from a demo run on ai-co-scientist.com." band />
        </>
      )}
      {cuts.map(c => <Sfx key={c} at={c} name="shutter" volume={0.5} />)}
      {stutter.map(c => <Sfx key={c} at={c} name="tick" volume={0.6} />)}
    </AbsoluteFill>
  );
};
