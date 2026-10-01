import React from 'react';
import {useCurrentFrame} from 'remotion';
import {WordReveal} from '../shared/WordReveal';
import {accel, emphasized, envelope, mix, ramp} from '../shared/motion';
import {C, MONO} from '../shared/tokens';
import {CHILDREN, FINAL_ELO, MATCHES, SEED_COUNT} from './data';

// Scene-local frame marks.
export const SPLIT = 0;
export const DEBATE = 110;
const MATCH_EVERY = 6;
export const EVOLVE = DEBATE + MATCHES.length * MATCH_EVERY + 6;
export const NETWORK_END = EVOLVE + 120;

const CX = 960;
const CY = 490;
const seat = (i: number, r = 330) => {
  const a = (i / SEED_COUNT) * Math.PI * 2 - Math.PI / 2;
  return {x: CX + Math.cos(a) * r * 1.45, y: CY + Math.sin(a) * r};
};

/** Elo of seed `i` after `m` matches: a steady walk from 1200 to its final value. */
const eloAt = (i: number, m: number) => Math.round(mix(1200, FINAL_ELO[i], Math.min(1, m / MATCHES.length)));

const Node: React.FC<{x: number; y: number; r: number; lit: number; label: string; sub?: string; opacity: number}> = ({x, y, r, lit, label, sub, opacity}) => (
  <div style={{position: 'absolute', left: x, top: y, opacity}}>
    <div
      style={{
        position: 'absolute',
        width: r * 2,
        height: r * 2,
        left: -r,
        top: -r,
        borderRadius: '50%',
        background: lit > 0 ? `rgba(94,200,190,${0.25 + 0.75 * lit})` : 'rgba(255,255,255,0.08)',
        border: `2px solid ${lit > 0 ? C.tealBright : 'rgba(255,255,255,0.55)'}`,
        boxShadow: lit > 0 ? `0 0 ${40 * lit}px rgba(94,200,190,${0.8 * lit})` : undefined,
      }}
    />
    <div style={{position: 'absolute', left: r + 16, top: -30, fontFamily: MONO, fontSize: 32, color: '#E8EAED', whiteSpace: 'nowrap', lineHeight: 1.1}}>
      {label}
      {sub && <div style={{fontSize: 26, color: lit > 0 ? C.tealBright : '#C4C7C5'}}>{sub}</div>}
    </div>
  </div>
);

/** One continuous take: a question splits into eight ideas, they debate, the best breed. */
export const Network: React.FC = () => {
  const f = useCurrentFrame();
  const m = Math.max(0, Math.min(MATCHES.length, (f - DEBATE) / MATCH_EVERY));
  const leave = ramp(f, NETWORK_END - 20, 20, accel);
  const pos = (i: number) => {
    const t = ramp(f, SPLIT + i * 2, 40, emphasized);
    const s = seat(i);
    const drift = Math.sin((f + i * 30) / 40) * 6;
    return {x: mix(CX, s.x, t), y: mix(CY, s.y, t) + drift, t};
  };
  const nodes = [...Array(SEED_COUNT)].map((_, i) => pos(i));
  const kids = CHILDREN.map(({parent}, ci) => {
    const t = ramp(f, EVOLVE + 10 + ci * 5, 34, emphasized);
    // Offspring settle inside the ring, off their parent's spoke, so no label meets the frame edge.
    const a = (parent / SEED_COUNT) * Math.PI * 2 - Math.PI / 2 + 0.32;
    const from = nodes[parent];
    return {from, x: mix(from.x, CX + Math.cos(a) * 185 * 1.45, t), y: mix(from.y, CY + Math.sin(a) * 185, t), t};
  });
  const cur = MATCHES[Math.min(MATCHES.length - 1, Math.floor(m))];
  return (
    <div style={{position: 'absolute', inset: 0, opacity: 1 - leave}}>
      <div style={{position: 'absolute', inset: 0, transform: `perspective(1800px) rotateX(${mix(0, 22, ramp(f, 30, 120, emphasized))}deg) rotateZ(${Math.sin(f / 90) * 2}deg) scale(${mix(1, 1.06, ramp(f, 0, NETWORK_END, t => t))})`, transformOrigin: '50% 55%'}}>
      <svg width={1920} height={1080} style={{position: 'absolute', inset: 0}}>
        {nodes.map((n, i) => (
          <line key={i} x1={CX} y1={CY} x2={n.x} y2={n.y} stroke="#fff" strokeOpacity={0.12 * n.t * (1 - ramp(f, DEBATE, 30))} strokeWidth={2} />
        ))}
        {MATCHES.map(([a, b], k) => {
          const at = DEBATE + k * MATCH_EVERY;
          const flash = ramp(f, at, 4) * (1 - ramp(f, at + 4, 18));
          const trace = ramp(f, at, 10);
          if (f < at) return null;
          const A = nodes[a];
          const B = nodes[b];
          const mx = (A.x + B.x) / 2 + (CY - (A.y + B.y) / 2) * 0.25;
          const my = (A.y + B.y) / 2 + ((A.x + B.x) / 2 - CX) * 0.25;
          return (
            <path key={k} d={`M${A.x} ${A.y} Q${mx} ${my} ${B.x} ${B.y}`} fill="none" stroke={C.tealBright} strokeOpacity={0.08 + 0.8 * flash} strokeWidth={2 + 3 * flash} pathLength={1} strokeDasharray={`${trace} 1`} />
          );
        })}
        {kids.map((k, i) => (
          <line key={i} x1={k.from.x} y1={k.from.y} x2={k.x} y2={k.y} stroke={C.tealBright} strokeOpacity={0.5 * k.t} strokeWidth={2} strokeDasharray="4 6" />
        ))}
      </svg>
      {nodes.map((n, i) => {
        const elo = eloAt(i, m);
        const lead = i === 0 ? ramp(f, DEBATE + 60, 60) : 0;
        const inMatch = f >= DEBATE && m < MATCHES.length && (cur[0] === i || cur[1] === i) ? 1 - ((f - DEBATE) % MATCH_EVERY) / MATCH_EVERY : 0;
        return <Node key={i} x={n.x} y={n.y} r={mix(10, 14 + (elo - 1080) / 14, n.t)} lit={Math.max(lead, inMatch * 0.6)} label={`H${i + 1}`} sub={f >= DEBATE - 10 ? `ELO ${elo}` : 'ELO 1200'} opacity={ramp(f, SPLIT, 10)} />;
      })}
      {kids.map((k, i) => (
        <Node key={`k${i}`} x={k.x} y={k.y} r={16} lit={0} label={`H${SEED_COUNT + 1 + i}`} sub="REFINED" opacity={k.t} />
      ))}
      </div>
      <div style={{position: 'absolute', left: 80, top: 64, fontFamily: MONO, fontSize: 32, color: '#BDC1C6', letterSpacing: '0.06em'}}>
        <div style={{opacity: envelope(f, 0, DEBATE, 10, 8)}}>GENERATION · {SEED_COUNT} HYPOTHESES</div>
        <div style={{opacity: envelope(f, DEBATE, EVOLVE, 10, 8), marginTop: -40}}>TOURNAMENT · MATCH {String(Math.min(MATCHES.length, Math.floor(m) + 1)).padStart(2, '0')} / {MATCHES.length}</div>
        <div style={{opacity: envelope(f, EVOLVE, NETWORK_END, 10, 8), marginTop: -40}}>EVOLUTION · {SEED_COUNT + Math.round(kids.reduce((a, k) => a + k.t, 0))} IDEAS</div>
      </div>
      <div style={{position: 'absolute', left: 0, right: 0, bottom: 70}}>
        <WordReveal text="Nine *hypotheses.*" start={20} end={DEBATE - 12} size={76} color="#F1F3F4" accentColor={C.tealBright} />
      </div>
      <div style={{position: 'absolute', left: 0, right: 0, bottom: 70}}>
        <WordReveal text="Debated *head to head.*" start={DEBATE + 6} end={EVOLVE - 12} size={76} color="#F1F3F4" accentColor={C.tealBright} />
      </div>
      <div style={{position: 'absolute', left: 0, right: 0, bottom: 70}}>
        <WordReveal text="The strongest *evolve.*" start={EVOLVE + 6} end={NETWORK_END - 16} size={76} color="#F1F3F4" accentColor={C.tealBright} />
      </div>
    </div>
  );
};
