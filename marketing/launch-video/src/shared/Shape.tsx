import React, {useId} from 'react';
// Imported, not copied: the landing page's own Material 3 Expressive shapes.
import {
  blendShapes,
  type ShapeName,
} from '../../../../app/frontend/src/workbench/pages/home_landing_shapes';

export type {ShapeName};

interface Props {
  from: ShapeName;
  to?: ShapeName;
  /** Morph progress 0-1 from `from` to `to`. */
  k?: number;
  size: number;
  fill: string;
  /** Second gradient stop; gives the shape a lit, tactile body instead of a flat fill. */
  fill2?: string;
  rotate?: number;
  style?: React.CSSProperties;
  children?: React.ReactNode;
}

export const Shape: React.FC<Props> = ({from, to, k = 0, size, fill, fill2, rotate = 0, style, children}) => {
  const id = useId();
  return (
  <div style={{position: 'relative', width: size, height: size, ...style}}>
    <svg
      width={size}
      height={size}
      viewBox="0 0 100 100"
      style={{position: 'absolute', inset: 0, transform: `rotate(${rotate}deg)`}}
    >
      {fill2 && (
        <defs>
          <linearGradient id={`g${id}`} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor={fill} />
            <stop offset="1" stopColor={fill2} />
          </linearGradient>
          <radialGradient id={`h${id}`} cx="0.32" cy="0.28" r="0.45">
            <stop offset="0" stopColor="#fff" stopOpacity="0.55" />
            <stop offset="1" stopColor="#fff" stopOpacity="0" />
          </radialGradient>
        </defs>
      )}
      <path d={blendShapes(from, to ?? from, k)} fill={fill2 ? `url(#g${id})` : fill} />
      {fill2 && <path d={blendShapes(from, to ?? from, k)} fill={`url(#h${id})`} />}
    </svg>
    {children && (
      <div
        style={{
          position: 'absolute',
          inset: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        {children}
      </div>
    )}
  </div>
  );
};
