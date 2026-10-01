import React from 'react';
import {FLASK_PATH} from './flask_path';

export const Flask: React.FC<{size: number; color: string; style?: React.CSSProperties}> = ({
  size,
  color,
  style,
}) => (
  <svg width={size} height={(size * 13) / 14} viewBox="0 0 14 13" style={style}>
    <path d={FLASK_PATH} fill={color} />
  </svg>
);
