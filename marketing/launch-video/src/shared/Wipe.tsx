import React from 'react';
import {useCurrentFrame} from 'remotion';
import {emphasized, ramp} from './motion';

/** A circle of `color` grows from (x, y) until it covers the frame: the film's light/dark hand-off. */
export const Wipe: React.FC<{color: string; dur?: number; x?: number; y?: number}> = ({color, dur = 24, x = 960, y = 490}) => {
  const f = useCurrentFrame();
  const r = ramp(f, 0, dur, emphasized) * 2300;
  return <div style={{position: 'absolute', left: x - r, top: y - r, width: r * 2, height: r * 2, borderRadius: '50%', background: color}} />;
};
