import React from 'react';
import {AbsoluteFill, Img, spring, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {StatusPill} from '../glide/Run';
import {Cursor} from '../shared/Cursor';
import {flaskSrc} from '../shared/HeroFlask';
import {PromptBox} from '../shared/PromptBox';
import {Shape, type ShapeName} from '../shared/Shape';
import {WordReveal} from '../shared/WordReveal';
import {accel, emphasized, mix, ramp} from '../shared/motion';
import {C, FONT, type Tone} from '../shared/tokens';
import {useBeats} from './Beat';
import {Sfx} from './Sfx';

type TileArt = {flask: Tone} | {shape: ShapeName; tone: Tone} | {ui: string; x: number; y: number; zoom: number};

// What a question becomes in this app: the glass flask, the agents' shapes,
// and crops of the real screens.
const TILES: TileArt[] = [
  {flask: 'teal'},
  {shape: 'cookie12', tone: 'teal'},
  {ui: 'ui/light-ideas.png', x: 0.09, y: 0.2, zoom: 4.2},
  {shape: 'flower', tone: 'blue'},
  {flask: 'yellow'},
  {ui: 'ui/light-overview.png', x: 0.18, y: 0.27, zoom: 4.6},
  {shape: 'gem', tone: 'red'},
  {flask: 'blue'},
];

/** A rounded square of art, the size of a word: the trailer's inline picture. */
const Tile: React.FC<{art: TileArt; size: number; f: number}> = ({art, size, f}) => (
  <div style={{width: size, height: size, borderRadius: size * 0.22, overflow: 'hidden', position: 'relative', flexShrink: 0, boxShadow: '0 12px 30px rgba(31,31,31,0.14)', background: 'flask' in art ? C.container[art.flask] : '#fff'}}>
    {'flask' in art && <Img src={flaskSrc(f, 30)} style={{position: 'absolute', width: size * 1.25, left: -size * 0.125, top: -size * 0.1}} />}
    {'shape' in art && (
      <div style={{position: 'absolute', inset: size * 0.08}}>
        <Shape from={art.shape} size={size * 0.84} fill={C.container[art.tone]} fill2={C.deep[art.tone]} rotate={f * 0.8} />
      </div>
    )}
    {'ui' in art && <Img src={staticFile(art.ui)} style={{position: 'absolute', width: size * art.zoom, left: -art.x * size * art.zoom, top: -art.y * size * art.zoom * 0.625}} />}
  </div>
);

/** Beats 4-7: "Every [picture] breakthrough", the picture column ticking up on every eighth note. */
export const EveryLine: React.FC = () => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const b = useBeats();
  const steps = [1, 2, 3, 4, 5].map(k => b(k * 0.5 + 0.5));
  const pos = steps.reduce((p, s) => p + ramp(f, s, 6, emphasized), 0);
  const size = 230;
  const gap = 34;
  const pop = spring({frame: f, fps, config: {damping: 13, stiffness: 160}});
  return (
    <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center'}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 48, fontFamily: FONT, fontSize: 132, fontWeight: 500, letterSpacing: '-0.03em', color: C.ink}}>
        <WordReveal text="Every" start={0} size={132} stagger={2} />
        <div style={{position: 'relative', width: size, height: size, transform: `scale(${pop})`}}>
          {TILES.map((art, i) => {
            const d = i - pos;
            if (Math.abs(d) > 2) return null;
            return (
              <div key={i} style={{position: 'absolute', left: 0, top: d * (size + gap), transform: `scale(${mix(1, 0.72, Math.min(1, Math.abs(d)))})`, opacity: mix(1, 0.4, Math.min(1, Math.abs(d))) * (1 - Math.max(0, Math.abs(d) - 1))}}>
                <Tile art={art} size={size} f={f} />
              </div>
            );
          })}
        </div>
        <WordReveal text="breakthrough" start={4} size={132} stagger={2} />
      </div>
      <Sfx at={0} name="pop0" volume={0.55} />
      {steps.map((s, k) => <Sfx key={s} at={s} name={`blip${k + 1}`} volume={0.32} />)}
    </AbsoluteFill>
  );
};

// Where each tile settles around the line, and how far it drifts while on screen.
const SCATTER = [
  [-700, -300, 0.9], [620, -330, 0.75], [-520, 290, 0.7], [760, 250, 0.95],
  [-860, 40, 0.55], [90, -390, 0.6], [180, 360, 0.65], [880, -60, 0.5],
];

/** Beats 7-9: "starts with a question.", the tiles bursting out around it. */
export const QuestionLine: React.FC = () => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  return (
    <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center'}}>
      {TILES.map((art, i) => {
        const [x, y, s] = SCATTER[i];
        const t = spring({frame: f - i, fps, config: {damping: 16, stiffness: 120}});
        const drift = 1 + f * 0.004;
        return (
          <div key={i} style={{position: 'absolute', left: 960 - 100, top: 540 - 100, transform: `translate(${x * t * drift}px, ${y * t * drift}px) scale(${s * t}) rotate(${(i % 2 ? 1 : -1) * 6 * (1 - t)}deg)`}}>
            <Tile art={art} size={200} f={f} />
          </div>
        );
      })}
      <WordReveal text="starts with a *question.*" start={0} size={132} stagger={2} />
      <Sfx at={0} name="whoosh" volume={0.55} />
    </AbsoluteFill>
  );
};

const GOAL = 'What mechanisms drive antibiotic resistance in S. aureus biofilms?';
const SPEED = 1.5;

/**
 * Beats 9-15: the composer blurs into focus, the goal is typed, and the click
 * lands on the bass drop-out at 8.31 s.
 */
export const Prompt: React.FC = () => {
  const f = useCurrentFrame();
  const b = useBeats();
  const focus = ramp(f, 0, b(1), emphasized);
  const typeAt = b(1);
  const typed = Math.ceil(GOAL.length / SPEED);
  const send = b(4);
  const lift = ramp(f, send + 4, 16, accel);
  const pill = ramp(f, b(5), 12, emphasized);
  const move = ramp(f, send - 16, 14, emphasized);
  const press = ramp(f, send, 3) * (1 - ramp(f, send + 3, 8));
  return (
    <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center'}}>
      <div style={{opacity: focus * (1 - lift), filter: `blur(${mix(36, 0, focus) + lift * 18}px)`, transform: `scale(${mix(0.82, 1, focus) * mix(1, 0.9, lift)}) translateY(${mix(0, -120, lift)}px)`, display: 'flex', flexDirection: 'column', alignItems: 'center'}}>
        <WordReveal text="What breakthrough should we make *today?*" start={4} size={70} weight={400} stagger={2} />
        <div style={{marginTop: 54, transform: 'scale(1.18)'}}>
          <PromptBox text={GOAL} start={typeAt} speed={SPEED} send={send} width={1240} fontSize={42} />
        </div>
      </div>
      <Cursor x={mix(1240, 1612, move)} y={mix(900, 680, move)} press={press} opacity={ramp(f, send - 20, 6) * (1 - ramp(f, send + 8, 6))} />
      <div style={{position: 'absolute', opacity: pill, transform: `scale(${mix(0.7, 1.3, pill)})`}}>
        <StatusPill label="Planning the research" f={f} />
      </div>
      <Sfx at={b(1) - 17} name="rise" volume={0.4} />
      {Array.from({length: Math.ceil(typed / 2)}, (_, k) => (
        <Sfx key={k} at={typeAt + k * 2} name={`key${(k * 7) % 4}`} volume={0.3 + 0.08 * ((k * 5) % 3)} />
      ))}
      <Sfx at={send} name="click" volume={0.8} />
      <Sfx at={send + 2} name="send" volume={0.5} />
      <Sfx at={b(5)} name="pop3" volume={0.35} />
    </AbsoluteFill>
  );
};
