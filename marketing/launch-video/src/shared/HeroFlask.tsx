import React from 'react';
import {Img, staticFile, useCurrentFrame} from 'remotion';

// public/hero holds a 120-frame Cycles render of a glass flask (blender/hero_flask.py),
// lit by brand-colored lights that orbit once, so the loop is seamless.
const LOOP = 120;

interface Props {
  /** Rendered size in px (the source is square). */
  size: number;
  x?: number;
  y?: number;
  opacity?: number;
  /** Shift into the loop so different films start on different highlights. */
  offset?: number;
  style?: React.CSSProperties;
}

/** The loop frame shown at film frame `f`. */
export const flaskSrc = (f: number, offset = 0) =>
  staticFile(`hero/flask_${String(((((Math.floor(f) + offset) % LOOP) + LOOP) % LOOP) + 1).padStart(4, '0')}.png`);

export const HeroFlask: React.FC<Props> = ({size, x = 0, y = 0, opacity = 1, offset = 0, style}) => {
  const f = useCurrentFrame();
  return (
    <Img
      src={flaskSrc(f, offset)}
      style={{position: 'absolute', left: 960 - size / 2 + x, top: 540 - size / 2 + y, width: size, height: size, opacity, ...style}}
    />
  );
};
