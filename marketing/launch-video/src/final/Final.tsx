import React from 'react';
import {AbsoluteFill, Sequence, useCurrentFrame} from 'remotion';
import {accel, ramp} from '../shared/motion';
import '../shared/fonts';
import {Arrive, Ask, End} from '../glide/Glide';
import {Agents, Ranked} from '../glide/Run';
import {Footnote} from '../shared/Footnote';
import {Wipe} from '../shared/Wipe';
import {C} from '../shared/tokens';
import {Checked, Leaderboard} from '../signal/Board';
import {NETWORK_END, Network} from '../signal/Network';
import {Rings} from '../signal/Rings';

// B's product story is the spine; C's tournament is what happens inside the
// run, so the film drops into the dark at "Running the tournament" and comes
// back to the real app to show the same result.
// Mirrored in score_final (scripts/score.py) so hits land on these cuts; keep in step.
const AGENTS_AT = 225;
const DARK_AT = 352;
const NETWORK_AT = 370;
const BOARD_AT = NETWORK_AT + NETWORK_END - 10;
const CHECK_AT = BOARD_AT + 150;
const LIGHT_AT = CHECK_AT + 118;
// The first app screen rides in on the tail of the light wipe, not after it.
const APP_AT = LIGHT_AT + 8;
// The report holds ~4 s here (Glide alone lets it run 7 s); the end card follows.
const APP_LEN = 400;
const END_AT = APP_AT + APP_LEN - 8;
export const FINAL_FRAMES = END_AT + 125;

const APP_CAPTIONS = [
  'The same ranking, live in the app.',
  'Every claim traced to its evidence.',
  'Every run ends in a report you can act on.',
] as const;

/** Fades its children out over the last frames of a scene of length `len`. */
const FadeOut: React.FC<{len: number; children: React.ReactNode}> = ({len, children}) => {
  const f = useCurrentFrame();
  return <AbsoluteFill style={{opacity: 1 - ramp(f, len - 18, 18, accel)}}>{children}</AbsoluteFill>;
};

/** The launch film: Glide's product walk-through with Signal's tournament inside it. */
export const Final: React.FC = () => (
  <AbsoluteFill style={{background: C.paper}}>
    <Sequence durationInFrames={140}><Arrive /></Sequence>
    <Sequence from={110} durationInFrames={125}><Ask /></Sequence>
    <Sequence from={AGENTS_AT} durationInFrames={145}><Agents /></Sequence>

    <Sequence from={DARK_AT} durationInFrames={NETWORK_AT - DARK_AT + 4}><Wipe color={C.night} /></Sequence>
    <Sequence from={NETWORK_AT} durationInFrames={APP_AT - NETWORK_AT}>
      <AbsoluteFill style={{background: C.night}}>
        <Rings />
      </AbsoluteFill>
    </Sequence>
    <Sequence from={NETWORK_AT} durationInFrames={NETWORK_END}><Network /></Sequence>
    <Sequence from={BOARD_AT} durationInFrames={150}><Leaderboard /></Sequence>
    <Sequence from={CHECK_AT} durationInFrames={130}><Checked /></Sequence>
    <Sequence from={NETWORK_AT} durationInFrames={LIGHT_AT - NETWORK_AT}>
      <Footnote text="Visualization of a demo run on ai-co-scientist.com. Sequences shortened." dark />
    </Sequence>
    <Sequence from={LIGHT_AT} durationInFrames={APP_AT - LIGHT_AT + 4}><Wipe color={C.paper} /></Sequence>

    <Sequence from={APP_AT} durationInFrames={APP_LEN}>
      <FadeOut len={APP_LEN}><Ranked captions={APP_CAPTIONS} /></FadeOut>
    </Sequence>
    <Sequence from={APP_AT} durationInFrames={END_AT - APP_AT}>
      <Footnote text="Screens from a demo run on ai-co-scientist.com. Sequences shortened." />
    </Sequence>
    <Sequence from={END_AT}><End /></Sequence>
  </AbsoluteFill>
);
