import React from 'react';
import {AbsoluteFill, Audio, staticFile} from 'remotion';
import '../shared/fonts';
import {Footnote} from '../shared/Footnote';
import {C} from '../shared/tokens';
import {EveryLine, Prompt, QuestionLine} from './Ask';
import {AtBeat} from './Beat';
import {Close, Wordmark} from './End';
import {Debate, Evolve, Generate, Rank} from './Loop';
import {OpenSwap, Title} from './Macro';
import {Montage} from './Montage';
import {Evidence, Ranked, Report} from './Proof';
import {STEM} from './Sfx';
import {Team, Working} from './Team';

export {LAUNCH_FRAMES} from './beats';

/**
 * The launch film: preview A's shapes and type with preview B's real app,
 * cut to the soundtrack of Google's Gemini Omni trailer. Scenes are placed in
 * beats (see beats.ts), so every cut lands on the music. The soundtrack is
 * fetched, never committed: scripts/fetch_soundtrack.sh.
 */
export const Launch: React.FC = () => (
  <AbsoluteFill style={{background: C.paper}}>
    {STEM !== 'sfx' && <Audio src={staticFile('audio/soundtrack.wav')} />}
    <AtBeat from={0} to={4}><Title /></AtBeat>
    <AtBeat from={4} to={7}><EveryLine /></AtBeat>
    <AtBeat from={7} to={9}><QuestionLine /></AtBeat>
    <AtBeat from={9} to={15}><Prompt /></AtBeat>
    <AtBeat from={15} to={21}><Team /></AtBeat>
    <AtBeat from={21} to={25}><Working /></AtBeat>
    <AtBeat from={25} to={29}><Generate /></AtBeat>
    <AtBeat from={29} to={33}><Debate /></AtBeat>
    <AtBeat from={33} to={37}><Evolve /></AtBeat>
    <AtBeat from={37} to={41}><Rank /></AtBeat>
    <AtBeat from={41} to={47}><Ranked /></AtBeat>
    <AtBeat from={47} to={53}><Evidence /></AtBeat>
    <AtBeat from={53} to={57}><Report /></AtBeat>
    <AtBeat from={57} to={65}><OpenSwap /></AtBeat>
    <AtBeat from={65} to={76}><Montage /></AtBeat>
    <AtBeat from={76} to={81}><Wordmark /></AtBeat>
    <AtBeat from={81}><Close /></AtBeat>
    <AtBeat from={25} to={37}><Footnote text="Ideas from a demo run on ai-co-scientist.com." /></AtBeat>
    <AtBeat from={37} to={41}><Footnote text="Illustrative tournament. Sequences shortened." /></AtBeat>
    <AtBeat from={41} to={47}><Footnote text="Screens from a demo run on ai-co-scientist.com." /></AtBeat>
    <AtBeat from={47} to={53}><Footnote text="Illustrative verdicts on an idea from the demo run." /></AtBeat>
    <AtBeat from={53} to={57}><Footnote text="Screens from a demo run on ai-co-scientist.com." /></AtBeat>
    <AtBeat from={65} to={76}><Footnote text="Screens from a demo run on ai-co-scientist.com. Sequences shortened." /></AtBeat>
  </AbsoluteFill>
);
