import React from 'react';
import {useCurrentFrame} from 'remotion';
import {FloatCard} from './FloatCard';
import {emphasized, mix, ramp} from './motion';
import {C, MONO} from './tokens';

// The ranked list in the live app's All Ideas tab (public/ui/*-ideas.png),
// cropped to its top three cards. Fractions of the 1600x1000 capture.
const CROP = {x: 0.045, y: 0.205, w: 0.265, h: 0.47};
// Card #1 inside that crop, as fractions of the crop.
const FIRST = {x: 0.045, y: 0.04, w: 0.917, h: 0.303};

interface Props {
  start: number;
  width: number;
  x: number;
  y?: number;
  /** Where the rating chip sits relative to the ringed card. */
  chip?: 'above' | 'right';
  dark?: boolean;
  /** Frame the winner is ringed; defaults to as soon as the list has landed. */
  ringAt?: number;
}

/** Real proof: the app's own ranked list, with the winner ringed and its rating called out. */
export const ProofList: React.FC<Props> = ({start, width, x, y = 0, chip = 'above', dark, ringAt = start + 26}) => {
  const f = useCurrentFrame();
  const inn = ramp(f, start, 26, emphasized);
  const ring = ramp(f, ringAt, 16, emphasized);
  const h = (width / 1.6) * (CROP.h / CROP.w);
  const left = 960 + x - width / 2;
  const top = 540 + y - h / 2 + mix(80, 0, inn);
  return (
    <>
      <FloatCard src={`ui/${dark ? 'dark' : 'light'}-ideas.png`} width={width} crop={CROP} x={x} y={y + mix(80, 0, inn)} ry={mix(-18, 0, inn)} opacity={inn} glow={0.9} dark={dark} />
      <div
        style={{
          position: 'absolute',
          left: left + FIRST.x * width - 10,
          top: top + FIRST.y * h - 10,
          width: FIRST.w * width + 20,
          height: FIRST.h * h + 20,
          borderRadius: 26,
          border: `5px solid ${dark ? C.tealBright : C.teal}`,
          boxShadow: `0 0 40px ${dark ? 'rgba(94,200,190,0.6)' : 'rgba(15,124,119,0.35)'}`,
          opacity: ring,
          transform: `scale(${mix(1.08, 1, ring)})`,
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: chip === 'right' ? left + width + 30 : left + FIRST.x * width,
          top: chip === 'right' ? top + FIRST.y * h + (FIRST.h * h) / 2 - 36 : top - 96,
          padding: '12px 26px',
          borderRadius: 999,
          background: dark ? C.tealBright : C.teal,
          color: dark ? C.night : '#fff',
          fontFamily: MONO,
          fontSize: 40,
          fontWeight: 500,
          opacity: ring,
          transform: `translateY(${mix(16, 0, ring)}px)`,
          whiteSpace: 'nowrap',
        }}
      >
        #1 · Elo 1386
      </div>
    </>
  );
};
