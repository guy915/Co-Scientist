import React from 'react';
import {AbsoluteFill, Audio, staticFile} from 'remotion';
import '../shared/fonts';
import {Footnote} from '../shared/Footnote';
import {C} from '../shared/tokens';
import {Prompt, Question} from './Ask';
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
    {STEM !== 'sfx' && <Audio src={staticFile('audio/soundtrack.wav')} />}
    <AtBeat from={0} to={4}><Title /></AtBeat>
    <AtBeat from={4} to={7}><Question /></AtBeat>
    <AtBeat from={7} to={15}><Prompt /></AtBeat>
    <AtBeat from={15} to={21}><Team /></AtBeat>
    <AtBeat from={21} to={25}><Working /></AtBeat>
    <AtBeat from={25} to={27}><VerbShot word="Generate." gloss="Hypotheses drafted from the literature" look={1} /></AtBeat>
    <AtBeat from={27} to={29}><Cards /></AtBeat>
    <AtBeat from={29} to={31}><VerbShot word="Debate." gloss="Ideas argue head to head" look={4} /></AtBeat>
    <AtBeat from={31} to={33}><Clash /></AtBeat>
    <AtBeat from={33} to={35}><VerbShot word="Evolve." gloss="The strongest are refined" look={3} /></AtBeat>
    <AtBeat from={35} to={37}><Child /></AtBeat>
    <AtBeat from={37} to={39}><VerbShot word="Rank." gloss="A tournament decides which lead" look={2} /></AtBeat>
    <AtBeat from={39} to={41}><Chart /></AtBeat>
    <AtBeat from={41} to={47}><Ranked /></AtBeat>
    <AtBeat from={47} to={53}><Evidence /></AtBeat>
    <AtBeat from={53} to={57}><Report /></AtBeat>
    <AtBeat from={57} to={65}><OpenSwap /></AtBeat>
    <AtBeat from={65} to={76}><Montage /></AtBeat>
    <AtBeat from={76} to={81}><Wordmark /></AtBeat>
    <AtBeat from={81}><Close /></AtBeat>
    {[27, 31, 35].map(at => (
      <AtBeat key={at} from={at} to={at + 2}><Footnote text="Ideas from a demo run on ai-co-scientist.com." /></AtBeat>
    ))}
    <AtBeat from={39} to={41}><Footnote text="Illustrative tournament. Sequences shortened." /></AtBeat>
    <AtBeat from={41} to={47}><Footnote text="Screens from a demo run on ai-co-scientist.com." /></AtBeat>
    <AtBeat from={47} to={51}><Footnote text="Illustrative verdicts on an idea from the demo run." /></AtBeat>
    <AtBeat from={51} to={57}><Footnote text="Screens from a demo run on ai-co-scientist.com." /></AtBeat>
    <AtBeat from={65} to={75}><Footnote text="Screens from a demo run on ai-co-scientist.com. Sequences shortened." /></AtBeat>
  </AbsoluteFill>
);
