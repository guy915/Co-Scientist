import React from 'react';
import {Freeze, useCurrentFrame} from 'remotion';
import {FPS} from '../shared/motion';
import {LAUNCH_FRAMES} from './beats';
import {Launch} from './Launch';

/** The upload master's frame rate; the film itself stays authored in FPS frames. */
export const MASTER_FPS = 60;

/** Studio default: plain 60 fps, one render per frame. */
export const MASTER_TIMES = Array.from({length: (LAUNCH_FRAMES * MASTER_FPS) / FPS}, (_, i) => (i * FPS) / MASTER_FPS);

/**
 * The film at arbitrary times: frame `m` is the film at `times[m]`, in film
 * (FPS) frames. scripts/render_master.py plans the times, several across each
 * 60 fps frame's shutter for motion blur, and averages them. Fractional times
 * are fine: every scene is a function of time, and springs and Freeze both
 * take them.
 */
export const Master: React.FC<{times: number[]}> = ({times}) => (
  <Freeze frame={times[useCurrentFrame()]}>
    <Launch />
  </Freeze>
);
