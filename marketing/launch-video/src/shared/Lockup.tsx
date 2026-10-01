import React from 'react';
import {useCurrentFrame} from 'remotion';
import {Flask} from './Flask';
import {mix, ramp} from './motion';
import {C, FONT, REPO, SITE} from './tokens';

interface Props {
  start: number;
  dark?: boolean;
  scale?: number;
  /** Multiplies every delay and duration; below 1 for an end card that must read in under 3 s. */
  pace?: number;
}

/** End card: flask + wordmark, then the URL and the open-source line, as every Google film closes. */
export const Lockup: React.FC<Props> = ({start, dark, scale = 1, pace = 1}) => {
  const f = useCurrentFrame();
  const icon = ramp(f, start, 18 * pace);
  const word = ramp(f, start + 6 * pace, 22 * pace);
  const meta = ramp(f, start + 24 * pace, 18 * pace);
  const ink = dark ? '#F1F3F4' : C.ink;
  const soft = dark ? '#BDC1C6' : C.inkSoft;
  return (
    <div style={{position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', fontFamily: FONT, transform: `scale(${scale})`}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 34}}>
        <Flask size={116} color={dark ? C.tealBright : C.teal} style={{opacity: icon, transform: `scale(${mix(0.6, 1, icon)}) rotate(${mix(-12, 0, icon)}deg)`}} />
        <div style={{fontSize: 124, fontWeight: 500, letterSpacing: '-0.03em', color: ink, opacity: word, filter: `blur(${mix(12, 0, word)}px)`, transform: `translateX(${mix(-30, 0, word)}px)`}}>
          Open Co-Scientist
        </div>
      </div>
      <div style={{marginTop: 54, textAlign: 'center', lineHeight: 1.45, opacity: meta, transform: `translateY(${mix(14, 0, meta)}px)`}}>
        <div style={{fontSize: 48, color: ink}}>
          Try it now at <span style={{color: dark ? C.tealBright : C.teal}}>{SITE}</span>
        </div>
        <div style={{fontSize: 36, color: soft, marginTop: 6}}>Open source on {REPO}</div>
      </div>
    </div>
  );
};
