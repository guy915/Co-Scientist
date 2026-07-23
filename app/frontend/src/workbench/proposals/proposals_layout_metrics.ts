// Base sizes and shared geometry types for the proposals graph layout.
//
// Every length below is a base size in CSS pixels. The layout multiplies all
// of them by one factor, chosen so the drawing exactly fits the stage: the
// page never scrolls, and nothing is ever transform-scaled, so text is drawn
// at a real font size rather than stretched.
//
// The row/ring placement lives in proposals_layout.ts and the edge routing
// in proposals_layout_routing.ts; both share these values so a size change
// here moves every part of the drawing together.

import {type ClusterId, type Edge} from './proposals_data';

/** Base node box. Labels wrap to at most two lines inside it. */
export const NODE_BASE = {width: 186, height: 54};

/**
 * Longest label drawn on a single line, in characters: the wrap length is
 * sized to NODE_BASE.width, so the two must move together.
 */
export const LABEL_WRAP_CHARS = 18;

/** One spacing value, used between clusters and around the rows. */
export const GAP_BASE = 40;

/** Space between the two rows. */
export const ROW_GAP_BASE = 48;

/** Breathing room between a cluster's outermost nodes and its hull. */
export const PAD_BASE = {
  x: NODE_BASE.width / 2 + 26,
  y: NODE_BASE.height / 2 + 32,
};

/** Smallest empty space allowed between two node boxes. */
export const CLEAR_BASE = 26;

/** Ring half-height at full size. */
export const RY_BASE = 96;

/**
 * Legend card width, in real pixels at every scale: the cards do not shrink
 * with the drawing. Fixed rather than measured, so the scale never depends
 * on a length that depends on the scale. The page hands this to CSS as
 * `--proposals-legend-width`, so the cards are exactly this wide.
 */
export const LEGEND_WIDTH = 200;

/** Used when the container has not been measured yet (tests, first paint). */
export const FALLBACK = {width: 1440, height: 760};

export interface Point {
  x: number;
  y: number;
}

export interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface EdgeGeometry {
  edge: Edge;
  /** SVG path data: a straight line, or a quadratic curve when offset. */
  path: string;
}

export interface Layout {
  width: number;
  height: number;
  /** Everything below is already multiplied by this; it also sizes type. */
  scale: number;
  node: {width: number; height: number};
  positions: Record<string, Point>;
  hulls: {id: ClusterId; label: string; bounds: Box}[];
  edges: EdgeGeometry[];
}

/** The space the graph has to work with, in CSS pixels. */
export interface Stage {
  width: number;
  height: number;
}
