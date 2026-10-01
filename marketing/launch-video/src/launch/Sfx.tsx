import React from 'react';
import {Audio, Sequence, getInputProps, staticFile} from 'remotion';

/** `--props='{"stem":"sfx"}'` renders the effects alone (or "music"), so the two can be checked apart. */
export const STEM = (getInputProps() as {stem?: 'mix' | 'sfx' | 'music'}).stem ?? 'mix';

interface Props {
  /** Scene-local frame the sound starts on. */
  at: number;
  /** A file in public/sfx, from scripts/sfx.py. */
  name: string;
  volume?: number;
}

/**
 * One sound effect, placed in the same scene as the motion it belongs to, so a
 * retimed scene carries its sounds with it.
 */
export const Sfx: React.FC<Props> = ({at, name, volume = 0.6}) =>
  STEM === 'music' ? null : (
    <Sequence from={at} durationInFrames={36} layout="none">
      <Audio src={staticFile(`sfx/${name}.wav`)} volume={volume} />
    </Sequence>
  );
