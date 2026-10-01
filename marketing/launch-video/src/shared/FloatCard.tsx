import React from 'react';
import {Img, staticFile} from 'remotion';

interface Props {
  src: string;
  width: number;
  /** Source aspect (w / h). The captures are 1600x1000. */
  aspect?: number;
  x?: number;
  y?: number;
  scale?: number;
  rx?: number;
  ry?: number;
  rz?: number;
  opacity?: number;
  /** 0-1 strength of the soft spectrum halo Google floats product UI on. */
  glow?: number;
  /** Crop window inside the image, in source-relative units (0-1). */
  crop?: {x: number; y: number; w: number; h: number};
  dark?: boolean;
  /** Depth-of-field blur in px, for handing focus to a foreground element. */
  blur?: number;
}

/** Real product UI floated in 3D space with a soft halo, in the style of the Gemini 3 / AI Mode films. */
export const FloatCard: React.FC<Props> = ({
  src,
  width,
  aspect = 1.6,
  x = 0,
  y = 0,
  scale = 1,
  rx = 0,
  ry = 0,
  rz = 0,
  opacity = 1,
  glow = 0.7,
  crop = {x: 0, y: 0, w: 1, h: 1},
  dark,
  blur = 0,
}) => {
  const h = (width / aspect) * (crop.h / crop.w);
  const imgW = width / crop.w;
  return (
    <div
      style={{
        position: 'absolute',
        left: '50%',
        top: '50%',
        width,
        height: h,
        marginLeft: -width / 2,
        marginTop: -h / 2,
        opacity,
        filter: blur ? `blur(${blur}px)` : undefined,
        transform: `perspective(2400px) translate3d(${x}px, ${y}px, 0) scale(${scale}) rotateX(${rx}deg) rotateY(${ry}deg) rotateZ(${rz}deg)`,
        transformStyle: 'preserve-3d',
      }}
    >
      <div
        style={{
          position: 'absolute',
          inset: -6,
          borderRadius: 30,
          background:
            'conic-gradient(from 200deg, #5EC8BE, #8AB4F8, #C4EED0, #FFE28A, #F6AEA9, #8AB4F8, #5EC8BE)',
          filter: 'blur(28px)',
          opacity: glow * (dark ? 0.55 : 0.45),
        }}
      />
      <div
        style={{
          position: 'absolute',
          inset: 0,
          borderRadius: 24,
          overflow: 'hidden',
          background: dark ? '#131314' : '#fff',
          boxShadow: dark
            ? '0 0 0 1px rgba(255,255,255,0.08)'
            : '0 0 0 1px rgba(31,31,31,0.06), 0 30px 80px rgba(31,31,31,0.10)',
        }}
      >
        <Img
          src={staticFile(src)}
          style={{
            position: 'absolute',
            width: imgW,
            left: -crop.x * imgW,
            top: -crop.y * (imgW / aspect),
          }}
        />
      </div>
    </div>
  );
};
