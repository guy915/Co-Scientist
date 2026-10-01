import React from 'react';
import {useCurrentFrame} from 'remotion';
import {mix, ramp} from './motion';
import {C, FONT} from './tokens';

interface Props {
  text: string;
  /** Frame typing starts. */
  start: number;
  /** Characters per frame. */
  speed?: number;
  /** Frame the send button is pressed. */
  send?: number;
  width?: number;
  dark?: boolean;
  placeholder?: string;
  fontSize?: number;
}

/** The app's composer, rebuilt as vectors so the goal can be typed live. */
export const PromptBox: React.FC<Props> = ({
  text,
  start,
  speed = 1.4,
  send,
  width = 1100,
  dark,
  placeholder = 'Start a new research goal to begin',
  fontSize = 34,
}) => {
  const f = useCurrentFrame();
  const n = Math.max(0, Math.floor((f - start) * speed));
  const shown = text.slice(0, n);
  const typing = n > 0 && n < text.length;
  const caret = typing || Math.floor(f / 15) % 2 === 0;
  const press = send === undefined ? 0 : ramp(f, send, 6) * (1 - ramp(f, send + 6, 10));
  const sent = send !== undefined && f >= send;
  const ink = dark ? '#E3E3E3' : C.ink;
  return (
    <div
      style={{
        width,
        borderRadius: 32,
        padding: '30px 34px 22px',
        fontFamily: FONT,
        background: dark ? '#1E1F20' : '#fff',
        boxShadow: dark
          ? '0 0 0 1px rgba(255,255,255,0.10)'
          : '0 0 0 1px rgba(31,31,31,0.08), 0 18px 50px rgba(31,31,31,0.08)',
      }}
    >
      <div style={{fontSize, lineHeight: 1.35, minHeight: fontSize * 2.7, color: shown ? ink : C.inkMute}}>
        {shown || placeholder}
        {!sent && caret && shown && (
          <span style={{display: 'inline-block', width: 3, height: fontSize * 1.1, marginLeft: 3, background: C.teal, verticalAlign: -6}} />
        )}
      </div>
      <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 10}}>
        <div style={{fontSize: 34, color: C.inkMute}}>+</div>
        <div
          style={{
            width: 58,
            height: 58,
            borderRadius: 29,
            background: n >= text.length ? C.teal : dark ? '#333537' : '#E9EEF1',
            transform: `scale(${mix(1, 0.86, press)})`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <svg width="28" height="28" viewBox="0 0 24 24">
            <path d="M4 12l1.4 1.4L11 7.8V20h2V7.8l5.6 5.6L20 12l-8-8z" fill="#fff" />
          </svg>
        </div>
      </div>
    </div>
  );
};
