import React from 'react';
import {AbsoluteFill, useCurrentFrame} from 'remotion';
import {AGENTS} from '../data/agents';
import {SEEDS} from '../data/demo_run';
import {EloChart} from '../shared/EloChart';
import {FloatCard} from '../shared/FloatCard';
import {IdeaCard} from '../shared/IdeaCard';
import {Shape} from '../shared/Shape';
import {C} from '../shared/tokens';
import {useBeats} from './Beat';
import {Backdrop, LOOKS} from './Macro';
import {Sfx} from './Sfx';

type Crop = {x: number; y: number; w: number; h: number};
type Shot = {ui: string; crop: Crop; width: number} | {art: 'agents' | 'chart' | 'idea'};

// Real screens from the demo run, each framed on the one region that reads at
// a glance, alternating with the film's own vector pieces. Crops are fractions
// of the 1600x1000 captures.
const SHOTS: Shot[] = [
  {ui: 'ui/light-home.png', crop: {x: 0.1, y: 0.1, w: 0.6, h: 0.42}, width: 1500},
  {ui: 'ui/dark-ideas.png', crop: {x: 0.045, y: 0.205, w: 0.265, h: 0.47}, width: 720},
  {art: 'idea'},
  {ui: 'ui/light-learning.png', crop: {x: 0.22, y: 0.22, w: 0.62, h: 0.42}, width: 1500},
  {art: 'agents'},
  {ui: 'ui/light-overview.png', crop: {x: 0.215, y: 0.23, w: 0.61, h: 0.25}, width: 1500},
  {ui: 'ui/dark-details.png', crop: {x: 0.215, y: 0.22, w: 0.58, h: 0.4}, width: 1500},
  {art: 'chart'},
  {ui: 'ui/light-ideas.png', crop: {x: 0.31, y: 0.2, w: 0.5, h: 0.42}, width: 1400},
  {ui: 'ui/dark-learning.png', crop: {x: 0.22, y: 0.22, w: 0.62, h: 0.42}, width: 1500},
  {ui: 'ui/light-details.png', crop: {x: 0.215, y: 0.22, w: 0.58, h: 0.4}, width: 1500},
];

const Art: React.FC<{kind: 'agents' | 'chart' | 'idea'; f: number}> = ({kind, f}) => {
  if (kind === 'idea')
    return (
      <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center', transform: `scale(${1.5 + f * 0.004})`}}>
        <IdeaCard tag={`#1 · Elo ${SEEDS[0].elo}`} title={SEEDS[0].title} width={760} lead />
      </AbsoluteFill>
    );
  if (kind === 'chart')
    return (
      <div style={{position: 'absolute', left: 300, top: 250, transform: `scale(${1 + f * 0.003})`}}>
        <EloChart start={-200} dur={1} width={1300} height={580} />
      </div>
    );
  return (
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
};

/**
 * Beats 65-76: a cut on every beat through the real app, each shot pushing in,
 * then four stutter frames of shapes into the breakdown.
 */
export const Montage: React.FC = () => {
  const f = useCurrentFrame();
  const b = useBeats();
  const cuts = SHOTS.map((_, i) => b(i));
  const stutter = [0, 1, 2, 3].map(k => b(10) + 5 + k * 4);
  const all = [...cuts, ...stutter];
  const i = all.filter(c => f >= c).length - 1;
  const local = f - all[i];
  const shot = SHOTS[i];
  return (
    <AbsoluteFill style={{background: C.paper}}>
      {i >= SHOTS.length ? (
        <Backdrop look={LOOKS[(i - SHOTS.length + 3) % LOOKS.length]} f={local * 6} />
      ) : 'ui' in shot ? (
        <FloatCard src={shot.ui} width={shot.width} crop={shot.crop} dark={shot.ui.includes('dark')} scale={1 + local * 0.006} ry={(i % 2 ? -1 : 1) * (4 - local * 0.3)} glow={0.9} />
      ) : (
        <Art kind={shot.art} f={local} />
      )}
      {cuts.map(c => <Sfx key={c} at={c} name="shutter" volume={0.5} />)}
      {stutter.map(c => <Sfx key={c} at={c} name="tick" volume={0.6} />)}
    </AbsoluteFill>
  );
};
