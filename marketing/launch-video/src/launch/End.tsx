import React from 'react';
import {AbsoluteFill, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {HeroFlask} from '../shared/HeroFlask';
import {Lockup} from '../shared/Lockup';
import {Shape} from '../shared/Shape';
import {accel, emphasized, mix, ramp} from '../shared/motion';
import {C, FONT} from '../shared/tokens';
import {useBeats} from './Beat';
import {Sfx} from './Sfx';

/**
 * Beats 76-81, the breakdown: the opening image again, flask on its shape,
 * the wordmark resolving on beat 1 and blurring away on beat 3, as the trailer
 * lets its name go before the final hit.
 */
export const Wordmark: React.FC = () => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const b = useBeats();
  const pop = spring({frame: f, fps, config: {damping: 14, stiffness: 110}});
  const rise = ramp(f, 0, 24, emphasized);
  const word = ramp(f, b(1), 16);
  // Still blurring away on the cut, so the end card lands on it rather than on blank white.
  const gone = ramp(f, b(3.5), b(5) - b(3.5) + 6, accel) * 0.85;
  return (
    <AbsoluteFill style={{opacity: 1 - gone, filter: `blur(${gone * 26}px)`}}>
      <div style={{position: 'absolute', left: 560 - 360, top: 540 - 360, transform: `scale(${pop * (1 + f * 0.0015)})`}}>
        <Shape from="cookie12" to="flower" k={ramp(f, 10, 50)} size={720} fill={C.container.teal} fill2={C.deep.teal} rotate={f * 0.5} />
      </div>
      <HeroFlask size={860} x={560 - 960} y={mix(200, -10, rise)} opacity={ramp(f, 0, 10)} offset={60} />
      <div style={{position: 'absolute', left: 1000, top: 540 - 80, display: 'flex', alignItems: 'center', gap: 30, fontFamily: FONT, opacity: word, filter: `blur(${mix(16, 0, word)}px)`, transform: `translateX(${mix(-30, 0, word)}px)`}}>
        <div style={{fontSize: 132, fontWeight: 500, letterSpacing: '-0.03em', color: C.ink, lineHeight: 1.05}}>
          Open
          <br />
          Co-Scientist
        </div>
      </div>
      <Sfx at={0} name="whoosh" volume={0.4} />
      <Sfx at={b(1)} name="sparkle" volume={0.45} />
    </AbsoluteFill>
  );
};

/** Beat 81 to the end: the end card lands on the final hit and builds fast enough to read. */
export const Close: React.FC = () => (
  <AbsoluteFill>
    <Lockup start={0} pace={0.45} scale={1.12} />
    <Sfx at={4} name="sparkle" volume={0.22} />
  </AbsoluteFill>
);

