import React from 'react';
import {Composition} from 'remotion';
import {EXPRESSIVE_FRAMES, Expressive} from './expressive/Expressive';
import {GLIDE_FRAMES, Glide} from './glide/Glide';
import {SIGNAL_FRAMES, Signal} from './signal/Signal';

const base = {fps: 30, width: 1920, height: 1080} as const;

export const RemotionRoot: React.FC = () => (
  <>
    <Composition id="A-Expressive" component={Expressive} durationInFrames={EXPRESSIVE_FRAMES} {...base} />
    <Composition id="B-Glide" component={Glide} durationInFrames={GLIDE_FRAMES} {...base} />
    <Composition id="C-Signal" component={Signal} durationInFrames={SIGNAL_FRAMES} {...base} />
  </>
);
