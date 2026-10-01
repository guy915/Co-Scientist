import React from 'react';
import {useCurrentFrame} from 'remotion';
import {ramp} from '../shared/motion';

/** Ambient line-art: concentric rings and a faint grid, the film's constant background. */
export const Rings: React.FC<{strength?: number}> = ({strength = 1}) => {
  const f = useCurrentFrame();
  const rings = [140, 260, 380, 520, 680, 860];
  return (
    <svg width={1920} height={1080} style={{position: 'absolute', inset: 0}}>
      {[...Array(13)].map((_, i) => (
        <line key={`v${i}`} x1={i * 160} x2={i * 160} y1={0} y2={1080} stroke="#fff" strokeOpacity={0.035 * strength} />
      ))}
      {[...Array(7)].map((_, i) => (
        <line key={`h${i}`} y1={i * 180} y2={i * 180} x1={0} x2={1920} stroke="#fff" strokeOpacity={0.035 * strength} />
      ))}
      {rings.map((r, i) => (
        <circle
          key={r}
          cx={960}
          cy={540}
          r={r * (0.92 + 0.08 * ramp(f, i * 4, 40))}
          fill="none"
          stroke="#fff"
          strokeOpacity={(0.09 - i * 0.01) * strength * ramp(f, i * 4, 30)}
          strokeDasharray={i % 2 ? '2 10' : undefined}
          transform={`rotate(${(i % 2 ? -1 : 1) * f * 0.06} 960 540)`}
        />
      ))}
    </svg>
  );
};
