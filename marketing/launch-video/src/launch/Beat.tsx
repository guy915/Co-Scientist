import React, {createContext, useContext} from 'react';
import {Sequence} from 'remotion';
import {B, LAUNCH_FRAMES} from './beats';

const Start = createContext(0);

/**
 * Mounts a scene from beat `from` until beat `to` (or the film's end); inside
 * it, `useBeats()` counts beats from the scene's start.
 */
export const AtBeat: React.FC<{from: number; to?: number; children: React.ReactNode}> = ({from, to, children}) => (
  <Sequence from={B(from)} durationInFrames={(to === undefined ? LAUNCH_FRAMES : B(to)) - B(from)}>
    <Start.Provider value={from}>{children}</Start.Provider>
  </Sequence>
);

/** Scene-local frame of the scene's `k`th beat. Scenes are written in beats, so moving one keeps it on the music. */
export const useBeats = () => {
  const b0 = useContext(Start);
  return (k: number) => B(b0 + k) - B(b0);
};

/** Hard cuts inside a scene: child `i` is mounted from `at[i]` until `at[i + 1]`, with its own frame count. */
export const Cuts: React.FC<{at: number[]; children: React.ReactNode[]}> = ({at, children}) => (
  <>
    {children.map((child, i) => (
      <Sequence key={at[i]} from={at[i]} durationInFrames={i + 1 < at.length ? at[i + 1] - at[i] : undefined}>
        {child}
      </Sequence>
    ))}
  </>
);
