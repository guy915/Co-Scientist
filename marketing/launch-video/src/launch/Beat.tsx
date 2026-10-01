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
