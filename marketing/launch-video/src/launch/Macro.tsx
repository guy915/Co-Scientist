import React from 'react';
import {AbsoluteFill, Img, useCurrentFrame} from 'remotion';
import {flaskSrc} from '../shared/HeroFlask';
import {Shape, type ShapeName} from '../shared/Shape';
import {TypeLine} from '../shared/TypeLine';
import {emphasized, mix, ramp} from '../shared/motion';
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

/**
 * One full-bleed shape frame; it drifts while on screen and is hard-cut away.
 * `enter` (0 to 1) slides each shape in from the side of the frame it sits on.
 */
export const Backdrop: React.FC<{look: Look; f: number; enter?: number; enter2?: number}> = ({look, f, enter = 1, enter2 = enter}) => {
  const big = 1900;
  const small = 640;
  // Unit vector from the frame's centre to the big shape; the small one sits mirrored, so it comes from the other side.
  const len = Math.hypot(look.x - 960, look.y - 540) || 1;
  const [dx, dy] = [(look.x - 960) / len, (look.y - 540) / len];
  const far = 1500 * (1 - enter);
  const far2 = 900 * (1 - enter2);
  return (
    <AbsoluteFill style={{background: C.paper, overflow: 'hidden'}}>
      <div style={{position: 'absolute', left: look.x - big / 2 + dx * far, top: look.y - big / 2 + dy * far, transform: `scale(${1 + f * 0.0016})`}}>
        <Shape from={look.shape} size={big} fill={C.container[look.tone]} fill2={C.deep[look.tone]} rotate={f * 0.35} />
      </div>
      <div style={{position: 'absolute', left: 1920 - look.x - small / 2 - dx * far2, top: 1080 - look.y - small / 2 - dy * far2, transform: `translateY(${-f * 0.8}px)`}}>
        <Shape from={look.shape2} size={small} fill={C.container[look.tone2]} fill2={C.deep[look.tone2]} rotate={-f * 0.6} />
      </div>
    </AbsoluteFill>
  );
};

/**
 * The trailer's title card: one big word over a full-bleed frame, a small chip
 * under it, cut in hard on the beat while the frame's shapes slide in from
 * their own sides.
 */
export const WordFrame: React.FC<{word: string; chip?: string; look: number}> = ({word, chip, look}) => {
  const f = useCurrentFrame();
  const settle = ramp(f, 0, 8);
  const tag = ramp(f, 4, 10);
  return (
    <AbsoluteFill>
      <Backdrop look={LOOKS[look % LOOKS.length]} f={f} enter={ramp(f, 0, 14, emphasized)} enter2={ramp(f, 3, 14, emphasized)} />
      <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center', fontFamily: FONT}}>
        <div style={{fontSize: 176, fontWeight: 500, letterSpacing: '-0.035em', color: C.ink, transform: `scale(${mix(1.06, 1, settle)})`}}>{word}</div>
        {chip && (
          <div style={{marginTop: 36, fontSize: 46, color: C.ink, background: 'rgba(255,255,255,0.86)', padding: '14px 34px', borderRadius: 999, opacity: tag, transform: `translateY(${mix(16, 0, tag)}px)`}}>
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

const SWAPS: {word: string; chip: string}[] = [
  {word: 'source.', chip: REPO},
  {word: 'science.', chip: 'PubMed · UniProt · Reactome · ChEMBL'},
  {word: 'to everyone.', chip: SITE},
];

const SIZE = 176;
const PAD = 34;

/** Width of `text` set as the swap's words, so the highlight can open to exactly fit it. */
const textWidth = (text: string) => {
  const ctx = document.createElement('canvas').getContext('2d');
  if (!ctx) return text.length * SIZE * 0.5;
  ctx.font = `500 ${SIZE}px 'Google Sans'`;
  return ctx.measureText(text).width - 0.035 * SIZE * text.length;
};

/**
 * The trailer's word-swap as one continuous shot: "Open" holds, and on every
 * second beat it eases left as a green highlight opens to its right, the new
 * word rolling in as the old one rolls out. Lands on the bass drop-out at 36.3 s.
 */
export const OpenSwap: React.FC = () => {
  const f = useCurrentFrame();
  const b = useBeats();
  const at = [b(2), b(4), b(6)];
  const k = at.filter(c => f >= c).length - 1;
  const t = k < 0 ? 0 : ramp(f, at[k], 14, emphasized);
  const widths = SWAPS.map(s => textWidth(s.word));
  const from = k > 0 ? widths[k - 1] + 2 * PAD : 0;
  const to = k >= 0 ? widths[k] + 2 * PAD : 0;
  const open = k > 0 ? 1 : t;
  const chipIn = k < 0 ? 0 : ramp(f, at[k] + 5, 10);
  const chipOut = k > 0 ? 1 - ramp(f, at[k], 6) : 0;
  const chip = (text: string, o: number, y: number) => (
    <div style={{position: 'absolute', top: 0, whiteSpace: 'nowrap', fontFamily: MONO, fontSize: 40, color: C.ink, background: 'rgba(255,255,255,0.86)', padding: '14px 34px', borderRadius: 999, opacity: o, transform: `translateY(${y}px)`}}>
      {text}
    </div>
  );
  return (
    <AbsoluteFill>
      <Backdrop look={LOOKS[5]} f={f + 40} />
      <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center', fontFamily: FONT}}>
        <div style={{display: 'flex', alignItems: 'center', fontSize: SIZE, fontWeight: 500, letterSpacing: '-0.035em', color: C.ink, lineHeight: 1.2}}>
          <div>Open</div>
          <div style={{width: mix(from, to, t), marginLeft: 40 * open, height: SIZE * 1.2, position: 'relative', overflow: 'hidden', borderRadius: 40, background: C.container.green}}>
            {SWAPS.map((s, i) => {
              if (i !== k && i !== k - 1) return null;
              // The first word is revealed by the highlight opening; later ones roll up through it.
              const y = k === 0 ? 0 : i === k ? mix(100, 0, t) : mix(0, -100, t);
              return (
                <div key={s.word} style={{position: 'absolute', left: PAD, top: 0, whiteSpace: 'nowrap', color: C.on.green, transform: `translateY(${y}%)`}}>
                  {s.word}
                </div>
              );
            })}
          </div>
        </div>
        <div style={{position: 'relative', height: 80, marginTop: 36, display: 'flex', justifyContent: 'center'}}>
          {k > 0 && chip(SWAPS[k - 1].chip, chipOut, 0)}
          {k >= 0 && chip(SWAPS[k].chip, chipIn, mix(16, 0, chipIn))}
        </div>
      </AbsoluteFill>
      <Sfx at={0} name="shutter" volume={0.55} />
      {at.map((c, i) => (
        <React.Fragment key={c}>
          <Sfx at={c + 2} name="swish" volume={0.45} />
          <Sfx at={c + 5} name={`pop${i + 4}`} volume={0.35} />
        </React.Fragment>
      ))}
    </AbsoluteFill>
  );
};
