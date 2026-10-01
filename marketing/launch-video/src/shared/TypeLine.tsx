import React from 'react';
import {useCurrentFrame} from 'remotion';
import {accel, ramp} from './motion';
import {C, FONT} from './tokens';

interface Props {
  text: string;
  start: number;
  end?: number;
  size?: number;
  color?: string;
  /** Frames between characters. */
  rate?: number;
  style?: React.CSSProperties;
}

/** The soft left-to-right letter fade Google uses for its one-line UI captions. */
export const TypeLine: React.FC<Props> = ({text, start, end, size = 54, color = C.teal, rate = 0.7, style}) => {
  const f = useCurrentFrame();
  const out = end === undefined ? 0 : ramp(f, end, 10, accel);
  return (
    <div style={{fontFamily: FONT, fontSize: size, fontWeight: 400, color, letterSpacing: '-0.01em', whiteSpace: 'pre', opacity: 1 - out, ...style}}>
      {[...text].map((ch, i) => (
        <span key={i} style={{opacity: ramp(f, start + i * rate, 8, t => t)}}>
          {ch}
        </span>
      ))}
    </div>
  );
};
