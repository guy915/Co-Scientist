import React from 'react';
import {FONT} from './tokens';

/**
 * The small disclosure Google's own launch films carry ("Sequences shortened…").
 * `band` lays a white fade under it, for shots where a screen runs to the bottom edge.
 */
export const Footnote: React.FC<{text: string; dark?: boolean; opacity?: number; band?: boolean}> = ({text, dark, opacity = 1, band}) => (
  <>
    {band && <div style={{position: 'absolute', left: 0, right: 0, bottom: 0, height: 96, background: 'linear-gradient(rgba(255,255,255,0), #fff 45%)', opacity}} />}
    <div style={{position: 'absolute', left: 0, right: 0, bottom: 22, textAlign: 'center', fontFamily: FONT, fontSize: 24, color: dark ? '#80868B' : '#80868B', opacity}}>
      {text}
    </div>
  </>
);
