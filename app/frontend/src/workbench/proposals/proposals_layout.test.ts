import {describe, expect, it} from 'vitest';
import {computeLayout} from './proposals_layout';

// A spread of shapes: wide desktop, laptop, short-and-wide, narrow, and the
// sizes a zoomed-in page reports (zooming shrinks the viewport in CSS px).
const STAGES = [
  {width: 1800, height: 900},
  {width: 1396, height: 700},
  {width: 1200, height: 520},
  {width: 900, height: 540},
  {width: 700, height: 420},
];

function bounds(stage: {width: number; height: number}) {
  const layout = computeLayout(stage);
  const boxes = layout.hulls.map(hull => hull.bounds);
  return {
    layout,
    left: Math.min(...boxes.map(box => box.x)),
    right: Math.max(...boxes.map(box => box.x + box.width)),
    top: Math.min(...boxes.map(box => box.y)),
    bottom: Math.max(...boxes.map(box => box.y + box.height)),
  };
}

describe('proposals layout', () => {
  it.each(STAGES)('fits inside a $width x $height stage', stage => {
    const {left, right, top, bottom} = bounds(stage);
    // Nothing may overflow: the page has no scrollbars in either axis, so a
    // drawing wider or taller than its stage would simply be cut off.
    expect(left).toBeGreaterThanOrEqual(0);
    expect(top).toBeGreaterThanOrEqual(0);
    expect(right).toBeLessThanOrEqual(stage.width + 0.5);
    expect(bottom).toBeLessThanOrEqual(stage.height + 0.5);
  });

  it.each(STAGES)('never scales above full size at $width', stage => {
    expect(computeLayout(stage).scale).toBeLessThanOrEqual(1);
  });

  it('leaves the same gap to each legend, at every size', () => {
    // The legend card is a fixed 12.5rem, which is exactly what the layout
    // reserves for it — so the two gaps are equal by construction rather
    // than by tuning, and stay equal as the drawing scales.
    const LEGEND = 200;
    for (const stage of STAGES) {
      const layout = computeLayout(stage);
      const row = layout.hulls
        .filter(hull => hull.id === 'evaluation' || hull.id === 'interaction')
        .sort((a, b) => a.bounds.x - b.bounds.x);
      const left = row[0].bounds.x - LEGEND;
      const right =
        stage.width - LEGEND - (row[1].bounds.x + row[1].bounds.width);
      expect(left).toBeCloseTo(right, 1);
    }
  });

  it('keeps the legends clear of the top row', () => {
    // The legends no longer shrink, so on a small stage they take a larger
    // share of it. The clusters must still start beyond them.
    for (const stage of STAGES) {
      const layout = computeLayout(stage);
      const row = layout.hulls
        .filter(hull => hull.id === 'evaluation' || hull.id === 'interaction')
        .sort((a, b) => a.bounds.x - b.bounds.x);
      expect(row[0].bounds.x).toBeGreaterThanOrEqual(200);
      expect(row[1].bounds.x + row[1].bounds.width).toBeLessThanOrEqual(
        stage.width - 200,
      );
    }
  });

  it('scales every length by the same factor', () => {
    const big = computeLayout({width: 1600, height: 900});
    const small = computeLayout({width: 800, height: 450});
    const ratio = small.scale / big.scale;
    expect(small.node.width / big.node.width).toBeCloseTo(ratio, 5);
    expect(small.node.height / big.node.height).toBeCloseTo(ratio, 5);
    expect(
      small.hulls[0].bounds.height / big.hulls[0].bounds.height,
    ).toBeCloseTo(ratio, 5);
  });
});
