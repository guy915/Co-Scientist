import React from 'react';
import {AbsoluteFill, Img, useCurrentFrame} from 'remotion';
import {flaskSrc} from '../shared/HeroFlask';
import {Shape, type ShapeName} from '../shared/Shape';
import {TypeLine} from '../shared/TypeLine';
import {mix, ramp} from '../shared/motion';
import {C, FONT, MONO, REPO, SITE, type Tone} from '../shared/tokens';
import {Cuts, useBeats} from './Beat';
import {Sfx} from './Sfx';

interface Look {
  shape: ShapeName;
  tone: Tone;
  /** A second, smaller shape in another tone, so each frame has depth. */
  shape2: ShapeName;
  tone2: Tone;
  x: number;
  y: number;
}

// Giant Expressive shapes cropped by the frame: the film's stand-in for the
// macro nature shots Google opens its launch films on.
export const LOOKS: Look[] = [
  {shape: 'cookie12', tone: 'teal', shape2: 'flower', tone2: 'blue', x: 1380, y: 820},
  {shape: 'flower', tone: 'blue', shape2: 'sunny', tone2: 'yellow', x: 520, y: 880},
  {shape: 'sunny', tone: 'yellow', shape2: 'gem', tone2: 'red', x: 1500, y: 260},
  {shape: 'clover', tone: 'green', shape2: 'cookie7', tone2: 'teal', x: 420, y: 240},
  {shape: 'gem', tone: 'red', shape2: 'clover', tone2: 'green', x: 1460, y: 900},
  {shape: 'cookie7', tone: 'blue', shape2: 'pill', tone2: 'yellow', x: 600, y: 160},
  {shape: 'pill', tone: 'yellow', shape2: 'cookie12', tone2: 'teal', x: 1300, y: 560},
];

/** One full-bleed shape frame; it drifts while on screen and is hard-cut away. */
export const Backdrop: React.FC<{look: Look; f: number}> = ({look, f}) => {
  const big = 1900;
  const small = 640;
  return (
    <AbsoluteFill style={{background: C.paper, overflow: 'hidden'}}>
      <div style={{position: 'absolute', left: look.x - big / 2, top: look.y - big / 2, transform: `scale(${1 + f * 0.0016})`}}>
        <Shape from={look.shape} size={big} fill={C.container[look.tone]} fill2={C.deep[look.tone]} rotate={f * 0.35} />
      </div>
      <div style={{position: 'absolute', left: 1920 - look.x - small / 2, top: 1080 - look.y - small / 2, transform: `translateY(${-f * 0.8}px)`}}>
        <Shape from={look.shape2} size={small} fill={C.container[look.tone2]} fill2={C.deep[look.tone2]} rotate={-f * 0.6} />
      </div>
    </AbsoluteFill>
  );
};

/**
 * The trailer's title card: one big word over a full-bleed frame, a small chip
 * under it, cut in hard on the beat and settling in a few frames.
 */
export const WordFrame: React.FC<{word: string; chip?: string; mono?: boolean; look: number; drift?: number}> = ({word, chip, mono, look, drift = 0}) => {
  const f = useCurrentFrame();
  const settle = ramp(f, 0, 8);
  const tag = ramp(f, 4, 10);
  return (
    <AbsoluteFill>
      <Backdrop look={LOOKS[look % LOOKS.length]} f={f + drift} />
      <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center', fontFamily: FONT}}>
        <div style={{fontSize: 176, fontWeight: 500, letterSpacing: '-0.035em', color: C.ink, transform: `scale(${mix(1.06, 1, settle)})`}}>{word}</div>
        {chip && (
          <div style={{marginTop: 36, fontFamily: mono ? MONO : FONT, fontSize: mono ? 40 : 46, color: C.ink, background: 'rgba(255,255,255,0.86)', padding: '14px 34px', borderRadius: 999, opacity: tag, transform: `translateY(${mix(16, 0, tag)}px)`}}>
            {chip}
          </div>
        )}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

/**
 * B's opening: the rendered glass flask stands in for the logo's flask glyph,
 * left of the name, with "Introducing" typed above the name as its eyebrow.
 */
const Mark: React.FC<{f: number; reveal: number}> = ({f, reveal}) => (
  <div style={{display: 'flex', alignItems: 'center', fontFamily: FONT}}>
    <Img src={flaskSrc(f)} style={{width: 330, height: 330, margin: '-60px -20px -60px -70px', opacity: reveal, transform: `scale(${mix(0.8, 1, reveal)})`}} />
    <div style={{display: 'flex', flexDirection: 'column', alignItems: 'flex-start'}}>
      <TypeLine text="Introducing" start={2} size={78} color={C.inkSoft} rate={1} style={{marginLeft: 8, marginBottom: -10}} />
      <div style={{fontSize: 150, fontWeight: 500, letterSpacing: '-0.03em', color: C.ink, opacity: reveal, filter: `blur(${mix(14, 0, reveal)}px)`}}>Open Co-Scientist</div>
    </div>
  </div>
);

/**
 * Beats 0-4, the quiet intro: B's opening line over the mark, while the shapes
 * behind cut on each beat, then stutter into the downbeat.
 */
export const Title: React.FC = () => {
  const f = useCurrentFrame();
  const b = useBeats();
  // Cut on beats 1-3, then four stutter frames into beat 4.
  const cuts = [0, b(1), b(2), b(3), b(3) + 4, b(3) + 8, b(3) + 12, b(3) + 16];
  const i = cuts.filter(c => f >= c).length - 1;
  return (
    <AbsoluteFill>
      <Backdrop look={LOOKS[i % LOOKS.length]} f={f - cuts[i] + i * 20} />
      <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center'}}>
        <Mark f={f} reveal={ramp(f, 0, 9)} />
      </AbsoluteFill>
      <Sfx at={0} name="sparkle" volume={0.2} />
      {cuts.slice(1, 4).map(c => <Sfx key={c} at={c} name="shutter" volume={0.5} />)}
      {cuts.slice(4).map(c => <Sfx key={c} at={c} name="tick" volume={0.6} />)}
    </AbsoluteFill>
  );
};

const SWAPS: {word: string; chip?: string}[] = [
  {word: 'Open'},
  {word: 'Open source.', chip: REPO},
  {word: 'Open science.', chip: 'PubMed · UniProt · Reactome · ChEMBL'},
  {word: 'Open to everyone.', chip: SITE},
];

/**
 * The trailer's word-swap: one composition, one word changing on the beat.
 * Lands on the bass drop-out at 36.3 s and swaps every second beat after it.
 */
export const OpenSwap: React.FC = () => {
  const b = useBeats();
  return (
    <Cuts at={[0, b(2), b(4), b(6)]}>
      {SWAPS.map((s, k) => (
        <React.Fragment key={s.word}>
          <WordFrame word={s.word} chip={s.chip} mono look={k} drift={k * 40} />
          <Sfx at={0} name="shutter" volume={0.55} />
          {s.chip && <Sfx at={4} name={`pop${k + 3}`} volume={0.35} />}
        </React.Fragment>
      ))}
    </Cuts>
  );
};
