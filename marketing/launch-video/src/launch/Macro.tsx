import React from 'react';
import {AbsoluteFill, useCurrentFrame} from 'remotion';
import {Flask} from '../shared/Flask';
import {Shape, type ShapeName} from '../shared/Shape';
import {mix, ramp} from '../shared/motion';
import {C, FONT, MONO, REPO, SITE, type Tone} from '../shared/tokens';
import {useBeats} from './Beat';
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

const Wordmark: React.FC<{size: number; reveal: number}> = ({size, reveal}) => (
  <div style={{display: 'flex', alignItems: 'center', gap: size * 0.26, fontFamily: FONT}}>
    <Flask size={size * 0.94} color={C.teal} style={{opacity: reveal, transform: `scale(${mix(0.7, 1, reveal)})`}} />
    <div style={{fontSize: size, fontWeight: 500, letterSpacing: '-0.03em', color: C.ink, opacity: reveal, filter: `blur(${mix(14, 0, reveal)}px)`}}>
      Open Co-Scientist
    </div>
  </div>
);

/**
 * Beats 0-4, the quiet intro: the wordmark holds while the shapes behind it
 * cut on each beat, then stutter into the downbeat.
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
        <Wordmark size={150} reveal={ramp(f, 0, 9)} />
      </AbsoluteFill>
      <Sfx at={0} name="sparkle" volume={0.2} />
      {cuts.slice(1, 4).map(c => <Sfx key={c} at={c} name="swish" volume={0.45} />)}
      {cuts.slice(4).map(c => <Sfx key={c} at={c} name="tick" volume={0.6} />)}
    </AbsoluteFill>
  );
};

const SWAPS: {word: string; chip?: string; look: number}[] = [
  {word: 'Open', look: 0},
  {word: 'Open source.', chip: REPO, look: 1},
  {word: 'Open science.', chip: 'PubMed · UniProt · Reactome · ChEMBL', look: 2},
  {word: 'Open to everyone.', chip: SITE, look: 3},
];

/**
 * The trailer's word-swap: one composition, one word changing on the beat.
 * Lands on the bass drop-out at 36.34 s and swaps on the stabs after it.
 */
export const OpenSwap: React.FC = () => {
  const f = useCurrentFrame();
  const b = useBeats();
  const at = [0, b(2), b(4), b(6)];
  const i = at.filter(c => f >= c).length - 1;
  const s = SWAPS[i];
  const local = f - at[i];
  const settle = ramp(local, 0, 8);
  const chip = ramp(local, 5, 10);
  return (
    <AbsoluteFill>
      <Backdrop look={LOOKS[s.look]} f={f + 60} />
      <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center', fontFamily: FONT}}>
        <div style={{fontSize: 168, fontWeight: 500, letterSpacing: '-0.035em', color: C.ink, transform: `scale(${mix(1.06, 1, settle)})`}}>{s.word}</div>
        {s.chip && (
          <div style={{marginTop: 40, fontFamily: MONO, fontSize: 40, color: C.ink, background: 'rgba(255,255,255,0.86)', padding: '14px 34px', borderRadius: 999, opacity: chip, transform: `translateY(${mix(16, 0, chip)}px)`}}>
            {s.chip}
          </div>
        )}
      </AbsoluteFill>
      {at.map((c, k) => (
        <React.Fragment key={c}>
          <Sfx at={c} name={k ? 'swish' : 'whoosh'} volume={0.5} />
          {SWAPS[k].chip && <Sfx at={c + 5} name={`pop${k + 3}`} volume={0.35} />}
        </React.Fragment>
      ))}
    </AbsoluteFill>
  );
};
