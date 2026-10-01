import React from 'react';
import {C, FONT, MONO} from './tokens';

interface Props {
  tag: string;
  title: string;
  width?: number;
  /** Highlight as the leader: teal ring and tag. */
  lead?: boolean;
  style?: React.CSSProperties;
}

/** A hypothesis as the app lists it: a tag line, then the title. */
export const IdeaCard: React.FC<Props> = ({tag, title, width = 700, lead, style}) => (
  <div
    style={{
      width,
      boxSizing: 'border-box',
      padding: '22px 30px',
      borderRadius: 26,
      background: '#fff',
      boxShadow: lead
        ? `0 0 0 4px ${C.teal}, 0 24px 60px rgba(15,124,119,0.22)`
        : '0 0 0 2px rgba(31,31,31,0.07), 0 18px 44px rgba(31,31,31,0.10)',
      fontFamily: FONT,
      ...style,
    }}
  >
    <div style={{fontFamily: MONO, fontSize: 26, fontWeight: 500, color: lead ? C.teal : C.inkMute}}>{tag}</div>
    <div style={{fontSize: 34, fontWeight: 500, color: C.ink, marginTop: 8, lineHeight: 1.22}}>{title}</div>
  </div>
);
