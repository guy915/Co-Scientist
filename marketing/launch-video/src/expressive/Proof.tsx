import React from 'react';
import {AbsoluteFill, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {EloChart} from '../shared/EloChart';
import {Footnote} from '../shared/Footnote';
import {ProofList} from '../shared/ProofList';
import {WordReveal} from '../shared/WordReveal';
import {envelope, mix, ramp} from '../shared/motion';
import {C, FONT, MONO} from '../shared/tokens';

/** 560-680: the tournament makes the ranking; one idea climbs clear. */
export const Rank: React.FC = () => {
  const f = useCurrentFrame();
  const vis = envelope(f, 0, 120, 14, 12);
  return (
    <AbsoluteFill style={{opacity: vis}}>
      <div style={{position: 'absolute', left: 150, top: 130}}>
        <WordReveal text="Ideas that *earn* their rank." start={0} size={104} align="left" />
      </div>
      <div style={{position: 'absolute', left: 280, top: 390}}>
        <EloChart start={10} dur={96} width={1360} height={540} />
      </div>
      <Footnote text="Illustrative tournament. Sequences shortened." />
    </AbsoluteFill>
  );
};

/** 680-780: the same story in the real app — the run's actual ranked list. */
export const RealRun: React.FC = () => {
  const f = useCurrentFrame();
  const vis = envelope(f, 0, 100, 12, 12);
  const sub = ramp(f, 14, 16);
  return (
    <AbsoluteFill style={{opacity: vis}}>
      <div style={{position: 'absolute', left: 150, top: 360, width: 820}}>
        <WordReveal text="Ranked, / in the *real* app." start={0} size={110} align="left" />
        <div style={{fontFamily: FONT, fontSize: 44, color: C.inkSoft, marginTop: 28, lineHeight: 1.3, opacity: sub, transform: `translateY(${mix(14, 0, sub)}px)`}}>
          15 ideas, 21 debates, one clear leader.
        </div>
      </div>
      <ProofList start={4} width={780} x={420} />
      <Footnote text="Screens from a demo run on ai-co-scientist.com." />
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

/** 780-875: every claim is checked against sources before the idea can rank. */
export const Evidence: React.FC = () => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const vis = envelope(f, 0, 95, 12, 12);
  const card = spring({frame: f - 6, fps, config: {damping: 15}});
  return (
    <AbsoluteFill style={{opacity: vis, alignItems: 'center'}}>
      <div style={{marginTop: 110}}>
        <WordReveal text="Every claim, checked against the *literature.*" start={0} size={88} />
      </div>
      <div style={{marginTop: 60, width: 1100, borderRadius: 32, background: '#fff', boxShadow: '0 0 0 2px rgba(31,31,31,0.06), 0 30px 70px rgba(31,31,31,0.10)', padding: '44px 54px', transform: `translateY(${mix(60, 0, card)}px)`, opacity: card, fontFamily: FONT}}>
        <div style={{fontSize: 44, fontWeight: 500, color: C.ink}}>Metabolic wake-up before vancomycin exposure</div>
        {CLAIMS.map((c, i) => {
          const chip = spring({frame: f - 24 - i * 7, fps, config: {damping: 12}});
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
          const t = ramp(f, 34 + i * 3, 14);
          return (
            <div key={s} style={{fontFamily: FONT, fontSize: 34, color: C.inkSoft, padding: '14px 30px', borderRadius: 999, background: C.paperTint, opacity: t, transform: `translateY(${mix(20, 0, t)}px)`}}>
              {s}
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
