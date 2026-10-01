import React from 'react';
import {mix} from './motion';

/** A pointer arrow; `press` 0-1 squashes it on click. */
export const Cursor: React.FC<{x: number; y: number; press?: number; opacity?: number}> = ({
  x,
  y,
  press = 0,
  opacity = 1,
}) => (
  <svg
    width="44"
    height="44"
    viewBox="0 0 24 24"
    style={{
      position: 'absolute',
      left: x,
      top: y,
      opacity,
      transform: `scale(${mix(1, 0.82, press)})`,
      transformOrigin: '0 0',
      filter: 'drop-shadow(0 4px 8px rgba(0,0,0,0.25))',
    }}
  >
    <path d="M4 2l15 11.5-6.6 1 3.8 7.4-2.8 1.4-3.8-7.5L4 20z" fill="#1F1F1F" stroke="#fff" strokeWidth="1.4" strokeLinejoin="round" />
  </svg>
);
