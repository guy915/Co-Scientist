import React from 'react';
import {useCurrentFrame} from 'remotion';
import {WordReveal} from '../shared/WordReveal';
import {accel, emphasized, envelope, mix, ramp} from '../shared/motion';
import {C, FONT, MONO} from '../shared/tokens';
import {BOARD, SOURCES} from './data';

/** The tournament resolves into the run's real leaderboard. */
export const Leaderboard: React.FC = () => {
  const f = useCurrentFrame();
  const out = ramp(f, 132, 18, accel);
  return (
    <div style={{position: 'absolute', inset: 0, opacity: 1 - out}}>
      <div style={{position: 'absolute', left: 170, top: 150}}>
        <WordReveal text="Until the best idea *rises.*" start={0} size={84} color="#F1F3F4" accentColor={C.tealBright} align="left" />
      </div>
      <div style={{position: 'absolute', left: 170, top: 320, fontFamily: MONO, fontSize: 30, letterSpacing: '0.06em', color: '#BDC1C6', opacity: ramp(f, 10, 14)}}>
        FINAL RANKING · 15 IDEAS · 21 MATCHES
      </div>
      {BOARD.map((row, i) => {
        const t = ramp(f, 14 + i * 5, 24, emphasized);
        const bar = ramp(f, 26 + i * 5, 40, emphasized);
        const top = i === 0;
        const w = ((row.elo - 1200) / 186) * 460;
        return (
          <div key={row.title} style={{position: 'absolute', left: 170, top: 400 + i * 100, display: 'flex', alignItems: 'center', opacity: t, transform: `translateX(${mix(-60, 0, t)}px)`}}>
            <div style={{width: 60, fontFamily: MONO, fontSize: 30, color: top ? C.tealBright : '#9AA0A6'}}>{i + 1}</div>
            <div style={{width: 980, whiteSpace: 'nowrap', fontFamily: FONT, fontSize: 30, color: top ? '#FFFFFF' : '#BDC1C6', fontWeight: top ? 500 : 400}}>{row.title}</div>
            <div style={{width: 480, height: 14, borderRadius: 7, background: 'rgba(255,255,255,0.06)'}}>
              <div style={{width: w * bar, height: 14, borderRadius: 7, background: top ? C.tealBright : 'rgba(255,255,255,0.35)', boxShadow: top ? '0 0 24px rgba(94,200,190,0.7)' : undefined}} />
            </div>
            <div style={{marginLeft: 26, fontFamily: MONO, fontSize: 30, color: top ? C.tealBright : '#BDC1C6'}}>{Math.round(mix(1200, row.elo, bar))}</div>
          </div>
        );
      })}
    </div>
  );
};

/** The winning idea's claims fan out to the databases that check them. */
export const Checked: React.FC = () => {
  const f = useCurrentFrame();
  const vis = envelope(f, 0, 130, 14, 16);
  const card = ramp(f, 4, 24, emphasized);
  const ox = 560;
  const oy = 560;
  return (
    <div style={{position: 'absolute', inset: 0, opacity: vis}}>
      <div style={{position: 'absolute', left: 0, right: 0, top: 120}}>
        <WordReveal text="Every claim, checked against the *literature.*" start={0} size={80} color="#F1F3F4" accentColor={C.tealBright} />
      </div>
      <svg width={1920} height={1080} style={{position: 'absolute', inset: 0}}>
        {SOURCES.map((s, i) => {
          const y = 330 + i * 92;
          const t = ramp(f, 24 + i * 5, 26, emphasized);
          return <path key={s} d={`M${ox + 330} ${oy} C ${ox + 560} ${oy}, ${1080} ${y}, ${1240} ${y}`} fill="none" stroke={C.tealBright} strokeOpacity={0.55} strokeWidth={2} pathLength={1} strokeDasharray={`${t} 1`} />;
        })}
      </svg>
      <div style={{position: 'absolute', left: ox - 330, top: oy - 110, width: 660, padding: '34px 40px', boxSizing: 'border-box', borderRadius: 24, border: `2px solid ${C.tealBright}`, background: 'rgba(94,200,190,0.08)', boxShadow: '0 0 60px rgba(94,200,190,0.25)', opacity: card, transform: `scale(${mix(0.92, 1, card)})`}}>
        <div style={{fontFamily: MONO, fontSize: 28, color: C.tealBright, letterSpacing: '0.06em'}}>#1 · ELO 1386</div>
        <div style={{fontFamily: FONT, fontSize: 38, color: '#fff', fontWeight: 500, marginTop: 10, lineHeight: 1.2}}>Metabolic wake-up before vancomycin exposure</div>
      </div>
      {SOURCES.map((s, i) => {
        const t = ramp(f, 40 + i * 5, 14);
        return (
          <div key={s} style={{position: 'absolute', left: 1260, top: 330 + i * 92 - 24, fontFamily: MONO, fontSize: 36, color: '#E8EAED', letterSpacing: '0.04em', opacity: t, display: 'flex', gap: 20, alignItems: 'center'}}>
            <span style={{color: C.tealBright, opacity: ramp(f, 60 + i * 5, 8)}}>✓</span>
            {s}
          </div>
        );
      })}
    </div>
  );
};
