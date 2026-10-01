import React from 'react';
import {useCurrentFrame} from 'remotion';
import {accel, mix, ramp} from './motion';
import {C, FONT} from './tokens';

export interface Word {
  text: string;
  accent?: boolean;
  /** Forces a line break before this word. */
  br?: boolean;
}

/** Parses "Every *great breakthrough* / starts here": *...* accents (may span words), a lone / breaks the line. */
export const words = (s: string): Word[] => {
  const out: Word[] = [];
  let br = false;
  let inAccent: boolean = false;
  for (const tok of s.split(' ')) {
    if (tok === '/') {
      br = true;
      continue;
    }
    const opens = tok.startsWith('*');
    const closes: boolean = tok.endsWith('*') && (tok.length > 1 || inAccent);
    const accent: boolean = inAccent || opens;
    out.push({text: tok.replace(/^\*|\*$/g, ''), accent, br});
    inAccent = accent && !closes;
    br = false;
  }
  return out;
};

interface Props {
  text: string;
  start: number;
  /** Frame the line starts leaving; omit to stay. */
  end?: number;
  size?: number;
  weight?: number;
  color?: string;
  accentColor?: string;
  stagger?: number;
  align?: 'center' | 'left';
  style?: React.CSSProperties;
}

/** Google-style headline: words rise and unblur one by one; the accent word carries the color. */
export const WordReveal: React.FC<Props> = ({
  text,
  start,
  end,
  size = 96,
  weight = 500,
  color = C.ink,
  accentColor = C.teal,
  stagger = 3,
  align = 'center',
  style,
}) => {
  const f = useCurrentFrame();
  const out = end === undefined ? 0 : ramp(f, end, 10, accel);
  const ws = words(text);
  const lines: Word[][] = [];
  ws.forEach(w => (w.br || lines.length === 0 ? lines.push([w]) : lines[lines.length - 1].push(w)));
  let i = 0;
  return (
    <div
      style={{
        fontFamily: FONT,
        fontSize: size,
        fontWeight: weight,
        letterSpacing: '-0.02em',
        lineHeight: 1.12,
        textAlign: align,
        color,
        opacity: 1 - out,
        transform: `translateY(${-24 * out}px)`,
        ...style,
      }}
    >
      {lines.map((line, li) => (
        <div key={li}>
          {line.map((w, wi) => {
            const t = ramp(f, start + i++ * stagger, 16);
            return (
              <span
                key={wi}
                style={{
                  display: 'inline-block',
                  marginRight: wi < line.length - 1 ? '0.26em' : 0,
                  opacity: t,
                  filter: `blur(${mix(10, 0, t)}px)`,
                  transform: `translateY(${mix(0.35, 0, t)}em)`,
                  color: w.accent ? accentColor : undefined,
                }}
              >
                {w.text}
              </span>
            );
          })}
        </div>
      ))}
    </div>
  );
};
