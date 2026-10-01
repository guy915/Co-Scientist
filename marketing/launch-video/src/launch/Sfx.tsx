import React from 'react';
import {Audio, Sequence, getInputProps, staticFile} from 'remotion';

/** `--props='{"stem":"sfx"}'` renders the effects alone (or "music"), so the two can be checked apart. */
export const STEM = (getInputProps() as {stem?: 'mix' | 'sfx' | 'music'}).stem ?? 'mix';

// Frames from a file's start to its audible peak. Air sounds swell, so they
// start early to peak on their frame; the rise swells into it and stops dead.
const LEAD: Record<string, number> = {swish: 4, whoosh: 7, rise: 16};

interface Props {
  /** Scene-local frame the sound hits on (its start, or its peak for swells). */
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
    <Sequence from={at - (LEAD[name] ?? 0)} durationInFrames={36} layout="none">
      <Audio src={staticFile(`sfx/${name}.wav`)} volume={volume} />
    </Sequence>
  );
