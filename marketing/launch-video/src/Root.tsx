import React from 'react';
import {Composition} from 'remotion';
import {EXPRESSIVE_FRAMES, Expressive} from './expressive/Expressive';
import {GLIDE_FRAMES, Glide} from './glide/Glide';
import {LAUNCH_FRAMES, Launch} from './launch/Launch';
import {MASTER_FPS, MASTER_TIMES, Master} from './launch/Master';
import {SIGNAL_FRAMES, Signal} from './signal/Signal';
import {FPS} from './shared/motion';

const base = {fps: FPS, width: 1920, height: 1080} as const;

export const RemotionRoot: React.FC = () => (
  <>
    <Composition id="Launch" component={Launch} durationInFrames={LAUNCH_FRAMES} {...base} />
    <Composition
      id="Launch-Master"
      component={Master}
      defaultProps={{times: MASTER_TIMES}}
      calculateMetadata={({props}) => ({fps: MASTER_FPS, durationInFrames: props.times.length})}
      durationInFrames={1}
      {...base}
    />
    <Composition id="A-Expressive" component={Expressive} durationInFrames={EXPRESSIVE_FRAMES} {...base} />
    <Composition id="B-Glide" component={Glide} durationInFrames={GLIDE_FRAMES} {...base} />
    <Composition id="C-Signal" component={Signal} durationInFrames={SIGNAL_FRAMES} {...base} />
  </>
);
