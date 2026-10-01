import React from 'react';
import {AbsoluteFill, Audio, staticFile} from 'remotion';
import '../shared/fonts';
import {C} from '../shared/tokens';
import {EveryLine, Prompt, QuestionLine} from './Ask';
import {AtBeat} from './Beat';
import {Close, Wordmark} from './End';
import {Cards, Chart, Child, Clash, VerbShot} from './Loop';
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
    {/* A quarter dB under unity: the music leads, a touch below the effects' ceiling. */}
    {STEM !== 'sfx' && <Audio src={staticFile('audio/soundtrack.wav')} volume={0.972} />}
    <AtBeat from={0} to={4}><Title /></AtBeat>
    <AtBeat from={4} to={6}><EveryLine /></AtBeat>
    <AtBeat from={6} to={8}><QuestionLine /></AtBeat>
    <AtBeat from={8} to={15}><Prompt /></AtBeat>
    <AtBeat from={15} to={21}><Team /></AtBeat>
    <AtBeat from={21} to={25}><Working /></AtBeat>
    <AtBeat from={25} to={27}><VerbShot word="Generate." gloss="Hypotheses drafted from the literature" look={1} /></AtBeat>
    <AtBeat from={27} to={29}><Cards /></AtBeat>
    <AtBeat from={29} to={31}><VerbShot word="Debate." gloss="Ideas argue head to head" look={4} /></AtBeat>
    <AtBeat from={31} to={33}><Clash /></AtBeat>
    <AtBeat from={33} to={35}><VerbShot word="Evolve." gloss="The strongest are refined" look={3} /></AtBeat>
    <AtBeat from={35} to={37}><Child /></AtBeat>
    <AtBeat from={37} to={39}><VerbShot word="Rank." gloss="A tournament decides which ideas lead" look={2} /></AtBeat>
    <AtBeat from={39} to={41}><Chart /></AtBeat>
    <AtBeat from={41} to={47}><Ranked /></AtBeat>
    <AtBeat from={47} to={53}><Evidence /></AtBeat>
    <AtBeat from={53} to={57}><Report /></AtBeat>
    <AtBeat from={57} to={65}><OpenSwap /></AtBeat>
    <AtBeat from={65} to={76}><Montage /></AtBeat>
    <AtBeat from={76} to={81}><Wordmark /></AtBeat>
    <AtBeat from={81}><Close /></AtBeat>
  </AbsoluteFill>
);
