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
type Shot = {ui: string; crop: Crop; width: number} | 'agents';

// Real screens from the demo run the film has not shown yet (home, run
// specification, idea detail, insights, other runs), in both themes, each framed
// on the one region that reads at a glance. Crops are fractions of the
// 1600x1000 captures.
const HERO = {x: 0.1, y: 0.1, w: 0.6, h: 0.42};
const SPECS = {x: 0.215, y: 0.22, w: 0.62, h: 0.4};
const DETAIL = {x: 0.33, y: 0.215, w: 0.47, h: 0.4};
const SHOTS: Shot[] = [
  {ui: 'ui/light-home.png', crop: HERO, width: 1500},
  {ui: 'ui/dark-details.png', crop: SPECS, width: 1500},
  {ui: 'ui/light-home.png', crop: {x: 0.79, y: 0.06, w: 0.2, h: 0.33}, width: 560},
  'agents',
  {ui: 'ui/light-ideas.png', crop: DETAIL, width: 1400},
  {ui: 'ui/dark-overview.png', crop: {x: 0.215, y: 0.23, w: 0.61, h: 0.25}, width: 1500},
  {ui: 'ui/light-overview.png', crop: {x: 0.215, y: 0.49, w: 0.6, h: 0.37}, width: 1500},
  {ui: 'ui/dark-home.png', crop: HERO, width: 1500},
  {ui: 'ui/light-details.png', crop: SPECS, width: 1500},
  {ui: 'ui/dark-ideas.png', crop: DETAIL, width: 1400},
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
          <FloatCard src={shot.ui} width={shot.width} crop={shot.crop} dark={shot.ui.includes('dark')} scale={1 + local * 0.006} ry={(i % 2 ? -1 : 1) * (4 - local * 0.3)} glow={0.9} fade={shot.crop.h > 0.3} />
          <Footnote text="Screens from a demo run on ai-co-scientist.com." band />
        </>
      )}
      {cuts.map(c => <Sfx key={c} at={c} name="shutter" volume={0.5} />)}
      {stutter.map(c => <Sfx key={c} at={c} name="tick" volume={0.6} />)}
    </AbsoluteFill>
  );
};
