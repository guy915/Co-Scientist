import React from 'react';
import {useCurrentFrame} from 'remotion';
import {MATCHES, eloSeries} from './elo';
import {ramp} from './motion';
import {C, FONT, MONO} from './tokens';

const SERIES = eloSeries();
const LO = 1080;
const HI = 1420;

interface Props {
  start: number;
  dur: number;
  width: number;
  height: number;
  dark?: boolean;
}

/** Eight rating lines drawn match by match; the leader is the brand teal and gets its number. */
export const EloChart: React.FC<Props> = ({start, dur, width, height, dark}) => {
  const f = useCurrentFrame();
  const p = ramp(f, start, dur, t => t);
  const upto = p * MATCHES;
  const X = (i: number) => (i / MATCHES) * width;
  const Y = (v: number) => height - ((v - LO) / (HI - LO)) * height;
  const line = (pts: number[]) => {
    const n = Math.floor(upto);
    const out = pts.slice(0, n + 1).map((v, i) => `${X(i)},${Y(v)}`);
    if (n < MATCHES) {
      const fr = upto - n;
      const v = pts[n] + (pts[n + 1] - pts[n]) * fr;
      out.push(`${X(n + fr)},${Y(v)}`);
    }
    return out.join(' ');
  };
  const lead = SERIES[0];
  const n = Math.min(MATCHES, Math.floor(upto));
  const tipV = lead[n];
  const grid = dark ? 'rgba(255,255,255,0.10)' : 'rgba(31,31,31,0.08)';
  const others = dark ? 'rgba(255,255,255,0.28)' : 'rgba(31,31,31,0.22)';
  return (
    <div style={{position: 'relative', width, height, fontFamily: FONT}}>
      <svg width={width} height={height} style={{overflow: 'visible'}}>
        {[1100, 1200, 1300, 1400].map(v => (
          <g key={v}>
            <line x1={0} x2={width} y1={Y(v)} y2={Y(v)} stroke={grid} strokeWidth={2} />
            <text x={-22} y={Y(v) + 10} textAnchor="end" fontFamily={MONO} fontSize={30} fill={dark ? '#9AA0A6' : C.inkMute}>
              {v}
            </text>
          </g>
        ))}
        {SERIES.slice(1).map((s, i) => (
          <polyline key={i} points={line(s)} fill="none" stroke={others} strokeWidth={3} strokeLinejoin="round" />
        ))}
        <polyline points={line(lead)} fill="none" stroke={dark ? C.tealBright : C.teal} strokeWidth={6} strokeLinejoin="round" strokeLinecap="round" />
        <circle cx={X(upto)} cy={Y(tipV)} r={11} fill={dark ? C.tealBright : C.teal} />
      </svg>
      <div
        style={{
          position: 'absolute',
          left: X(upto) + 24,
          top: Y(tipV) - 40,
          fontFamily: MONO,
          fontSize: 56,
          fontWeight: 500,
          color: dark ? C.tealBright : C.teal,
        }}
      >
        {Math.round(tipV)}
      </div>
    </div>
  );
};
