import type {HTMLAttributes, ReactNode} from 'react';
import {joinClasses} from './cx';

export type CardTone = 'neutral' | 'raised' | 'warning' | 'danger';
export type CardSize = 'block' | 'tile' | 'panel';

// Cards are tonal layers, never shadows (elevation is for overlays). A block
// is a notice, a tile a stat or summary, and a panel groups controls.
const TONE_CLASSES: Record<CardTone, string> = {
  neutral: 'bg-cosci-panel text-cosci-fg',
  raised: 'bg-cosci-settings-card-bg text-cosci-fg',
  warning: 'bg-th-warning-container text-th-on-warning-container',
  danger:
    'border border-cosci-danger-border bg-cosci-danger-bg text-cosci-danger-fg',
};

const SIZE_CLASSES: Record<CardSize, string> = {
  block: 'rounded-md px-4 py-3',
  tile: 'rounded-md p-4',
  panel: 'rounded-2xl px-[1.4rem] pt-5 pb-[1.4rem]',
};

export interface CardStyle {
  tone?: CardTone;
  size?: CardSize;
  outlined?: boolean;
}

export function cardClasses({
  tone = 'neutral',
  size = 'block',
  outlined = false,
}: CardStyle = {}): string {
  return joinClasses(
    TONE_CLASSES[tone],
    SIZE_CLASSES[size],
    outlined && tone !== 'danger' && 'border border-cosci-border',
  );
}

export function Card({
  tone,
  size,
  outlined,
  as: Tag = 'div',
  layoutClassName,
  children,
  ...rest
}: CardStyle &
  Omit<HTMLAttributes<HTMLElement>, 'className'> & {
    as?: 'div' | 'section' | 'article' | 'aside';
    layoutClassName?: string;
    children: ReactNode;
  }) {
  return (
    <Tag
      className={joinClasses(
        cardClasses({tone, size, outlined}),
        layoutClassName,
      )}
      {...rest}
    >
      {children}
    </Tag>
  );
}
