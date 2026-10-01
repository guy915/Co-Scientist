import React from 'react';
import {FONT} from './tokens';

/** The small disclosure Google's own launch films carry ("Sequences shortened…"). */
export const Footnote: React.FC<{text: string; dark?: boolean; opacity?: number}> = ({text, dark, opacity = 1}) => (
  <div style={{position: 'absolute', left: 0, right: 0, bottom: 22, textAlign: 'center', fontFamily: FONT, fontSize: 24, color: dark ? '#80868B' : '#80868B', opacity}}>
    {text}
  </div>
);
