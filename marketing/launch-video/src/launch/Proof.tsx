import React from 'react';
import {AbsoluteFill, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {FloatCard} from '../shared/FloatCard';
import {ProofList} from '../shared/ProofList';
import {WordReveal} from '../shared/WordReveal';
import {accel, emphasized, mix, ramp} from '../shared/motion';
import {C, FONT, MONO} from '../shared/tokens';
import {useBeats} from './Beat';
import {Sfx} from './Sfx';

/** Beats 41-47: the run's real ranked list; the winner is ringed on the 28.70 s stab. */
export const Ranked: React.FC = () => {
  const f = useCurrentFrame();
  const b = useBeats();
  const ringAt = b(4);
  const sub = ramp(f, b(1), 14);
  return (
    <AbsoluteFill>
      <div style={{position: 'absolute', left: 150, top: 360, width: 820}}>
        <WordReveal text="Ranked, / in the *real* app." start={0} size={110} align="left" stagger={2} />
        <div style={{fontFamily: FONT, fontSize: 44, color: C.inkSoft, marginTop: 28, lineHeight: 1.3, opacity: sub, transform: `translateY(${mix(14, 0, sub)}px)`}}>
          15 ideas, 21 debates, one clear leader.
        </div>
      </div>
      <ProofList start={2} width={780} x={420} ringAt={ringAt} />
      <Sfx at={2} name="whoosh" volume={0.45} />
      <Sfx at={ringAt} name="ding" volume={0.55} />
      <Sfx at={ringAt + 3} name="pop6" volume={0.35} />
    </AbsoluteFill>
  );
};

// Sources are real tools the reference MCP server exposes.
const SOURCES = ['PubMed', 'UniProt', 'Reactome', 'ClinicalTrials.gov', 'Open Targets', 'ChEMBL'];
const CLAIMS = [
  {w: 600, verdict: 'supports', tone: C.container.green, ink: C.on.green},
  {w: 520, verdict: 'partial', tone: C.container.yellow, ink: C.on.yellow},
  {w: 560, verdict: 'supports', tone: C.container.green, ink: C.on.green},
];

/** Beats 47-53: each claim's verdict pops on a beat, the first on the 31.23 s stab. */
export const Evidence: React.FC = () => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const b = useBeats();
  const card = spring({frame: f - 2, fps, config: {damping: 15, stiffness: 140}});
  const chips = [b(2), b(3), b(4)];
  const sources = SOURCES.map((_, i) => b(4.5 + i * 0.25));
  return (
    <AbsoluteFill style={{alignItems: 'center'}}>
      <div style={{marginTop: 110}}>
        <WordReveal text="Every claim, checked against the *literature.*" start={0} size={88} stagger={2} />
      </div>
      <div style={{marginTop: 60, width: 1100, borderRadius: 32, background: '#fff', boxShadow: '0 0 0 2px rgba(31,31,31,0.06), 0 30px 70px rgba(31,31,31,0.10)', padding: '44px 54px', transform: `translateY(${mix(70, 0, card)}px)`, opacity: Math.min(1, card * 1.5), fontFamily: FONT}}>
        <div style={{fontSize: 44, fontWeight: 500, color: C.ink}}>Metabolic wake-up before vancomycin exposure</div>
        {CLAIMS.map((c, i) => {
          const chip = spring({frame: f - chips[i], fps, config: {damping: 11, stiffness: 180}});
          return (
            <div key={i} style={{display: 'flex', alignItems: 'center', gap: 28, marginTop: 30}}>
              <div style={{height: 18, width: c.w, borderRadius: 9, background: '#E3E8EC'}} />
              <div style={{fontFamily: MONO, fontSize: 34, padding: '10px 26px', borderRadius: 999, background: c.tone, color: c.ink, transform: `scale(${chip})`}}>{c.verdict}</div>
            </div>
          );
        })}
      </div>
      <div style={{display: 'flex', gap: 18, marginTop: 50}}>
        {SOURCES.map((s, i) => {
          const t = ramp(f, sources[i], 8, emphasized);
          return (
            <div key={s} style={{fontFamily: FONT, fontSize: 34, color: C.inkSoft, padding: '14px 30px', borderRadius: 999, background: C.paperTint, opacity: t, transform: `translateY(${mix(20, 0, t)}px)`}}>
              {s}
            </div>
          );
        })}
      </div>
      <Sfx at={2} name="swish" volume={0.4} />
      {chips.map((c, i) => <Sfx key={c} at={c} name={`pop${[3, 2, 4][i]}`} volume={0.4} />)}
      {sources.map(s => <Sfx key={s} at={s} name="tick" volume={0.35} />)}
    </AbsoluteFill>
  );
};

// The overview tab's summary row: ideas explored, verified, sources analysed.
const REPORT_CROP = {x: 0.215, y: 0.23, w: 0.61, h: 0.25};

/** Beats 53-57: the report, which then pinches to a blurred pill to hand off to the drop. */
export const Report: React.FC = () => {
  const f = useCurrentFrame();
  const b = useBeats();
  const inn = ramp(f, 0, 18, emphasized);
  const pinch = ramp(f, b(3) - 6, b(4) - b(3) + 6, accel);
  return (
    <AbsoluteFill>
      <div style={{position: 'absolute', left: 0, right: 0, top: 150, opacity: 1 - pinch}}>
        <WordReveal text="A report you can *act on.*" start={0} size={96} stagger={2} />
      </div>
      <FloatCard
        src="ui/light-overview.png"
        width={1500}
        crop={REPORT_CROP}
        y={mix(160, 90, inn)}
        scale={mix(0.92, 1, inn) * (1 + f * 0.0008) * mix(1, 0.3, pinch)}
        ry={mix(-14, 0, inn)}
        opacity={inn * (1 - pinch * 0.6)}
        blur={pinch * 40}
        glow={mix(0.9, 1.4, pinch)}
      />
      <Sfx at={0} name="whoosh" volume={0.45} />
      <Sfx at={b(4) - 17} name="rise" volume={0.45} />
    </AbsoluteFill>
  );
};
