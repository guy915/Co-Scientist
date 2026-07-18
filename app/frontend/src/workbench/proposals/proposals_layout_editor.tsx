// TEMPORARY: a layout editor for /proposals, reached with ?edit=1.
//
// The graph is treated as one object: drag anywhere to move the whole thing,
// drag the corner handle to resize the whole thing. Both gestures only
// change which region of the canvas is on screen, so the result is a single
// viewBox to paste into proposals_layout.ts as CANVAS. Once the framing is
// committed this file and its call sites in proposals_page.tsx should go.

import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {clusters} from './proposals_data';
import {CANVAS, clusterBounds, type Box} from './proposals_layout';

/** The drawing's own extent, which the corner handle is anchored to. */
const CONTENT: Box = (() => {
  const boxes = clusters.map(cluster => clusterBounds(cluster.id));
  const x = Math.min(...boxes.map(box => box.x));
  const y = Math.min(...boxes.map(box => box.y));
  return {
    x,
    y,
    width: Math.max(...boxes.map(box => box.x + box.width)) - x,
    height: Math.max(...boxes.map(box => box.y + box.height)) - y,
  };
})();

/** The view box, formatted to paste straight into proposals_layout.ts. */
function printView(view: Box): string {
  const round = Math.round;
  return (
    'export const CANVAS: Box = {' +
    `x: ${round(view.x)}, y: ${round(view.y)}, ` +
    `width: ${round(view.width)}, height: ${round(view.height)}};`
  );
}

type Drag =
  | {kind: 'pan'; from: {x: number; y: number}; view: Box; unitsPerPx: number}
  | {kind: 'zoom'; from: {x: number; y: number}; view: Box; unitsPerPx: number};

/**
 * Editing state and the handles drawn over the graph.
 *
 * @returns The live view box, the SVG overlay, and the readout panel.
 */
export function useLayoutEditor() {
  const [view, setView] = useState<Box>(CANVAS);
  // Every gesture pushes the state it started from, so undo steps back one
  // drag rather than one pointer sample.
  const [history, setHistory] = useState<Box[]>([]);
  const drag = useRef<Drag | null>(null);

  const undo = useCallback(() => {
    setHistory(past => {
      if (past.length === 0) return past;
      setView(past[past.length - 1]);
      return past.slice(0, -1);
    });
  }, []);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== 'z' || !(event.metaKey || event.ctrlKey)) return;
      event.preventDefault();
      undo();
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [undo]);

  // Deltas are measured in screen pixels and converted with the ratio taken
  // at the start of the gesture. Reading canvas coordinates live would feed
  // the view's own change back into the next sample.
  const beginDrag = useCallback(
    (kind: Drag['kind'], event: React.PointerEvent<SVGElement>) => {
      const svg = event.currentTarget.ownerSVGElement;
      const rendered = svg?.getBoundingClientRect().width ?? 1;
      event.currentTarget.setPointerCapture(event.pointerId);
      setHistory(past => [...past, view]);
      drag.current = {
        kind,
        from: {x: event.clientX, y: event.clientY},
        view,
        unitsPerPx: view.width / rendered,
      };
    },
    [view],
  );

  const onPointerMove = useCallback((event: React.PointerEvent<SVGElement>) => {
    const active = drag.current;
    if (!active) return;
    const dx = (event.clientX - active.from.x) * active.unitsPerPx;
    const dy = (event.clientY - active.from.y) * active.unitsPerPx;

    if (active.kind === 'pan') {
      // Moving the drawing right means looking further left.
      setView({...active.view, x: active.view.x - dx, y: active.view.y - dy});
      return;
    }

    // The handle sits at the drawing's bottom-right and grows it about its
    // top-left, so dragging out enlarges everything. A smaller view box is
    // what "bigger" means: the same drawing fills more of the screen.
    const pivot = {x: CONTENT.x, y: CONTENT.y};
    const corner = {
      x: CONTENT.x + CONTENT.width,
      y: CONTENT.y + CONTENT.height,
    };
    const ratioX = (corner.x + dx - pivot.x) / CONTENT.width;
    const ratioY = (corner.y + dy - pivot.y) / CONTENT.height;
    const scale = Math.min(4, Math.max(0.25, (ratioX + ratioY) / 2));
    setView({
      x: pivot.x - (pivot.x - active.view.x) / scale,
      y: pivot.y - (pivot.y - active.view.y) / scale,
      width: active.view.width / scale,
      height: active.view.height / scale,
    });
  }, []);

  const endDrag = useCallback((event: React.PointerEvent<SVGElement>) => {
    drag.current = null;
    event.currentTarget.releasePointerCapture(event.pointerId);
  }, []);

  const overlay = useMemo(
    () => (
      <g className="proposals-editor">
        {/* Anywhere on the canvas moves the whole drawing. */}
        <rect
          className="proposals-editor-move"
          x={view.x}
          y={view.y}
          width={view.width}
          height={view.height}
          onPointerDown={event => beginDrag('pan', event)}
          onPointerMove={onPointerMove}
          onPointerUp={endDrag}
        />
        {/* The drawing's own extent, so its edges are visible while framing. */}
        <rect
          className="proposals-editor-extent"
          x={CONTENT.x}
          y={CONTENT.y}
          width={CONTENT.width}
          height={CONTENT.height}
          rx={28}
        />
        <rect
          className="proposals-editor-resize"
          x={CONTENT.x + CONTENT.width - 22}
          y={CONTENT.y + CONTENT.height - 22}
          width={20}
          height={20}
          rx={4}
          onPointerDown={event => beginDrag('zoom', event)}
          onPointerMove={onPointerMove}
          onPointerUp={endDrag}
        />
      </g>
    ),
    [view, beginDrag, onPointerMove, endDrag],
  );

  const panel = (
    <div className="proposals-editor-panel">
      <p>
        Drag anywhere to move the whole graph. Drag the corner square to resize
        it. Ctrl/Cmd+Z undoes. When it looks right, copy this over CANVAS in
        proposals_layout.ts.
      </p>
      <textarea readOnly rows={3} value={printView(view)} />
      <div className="proposals-editor-actions">
        <button
          type="button"
          className="ucs-panel-button"
          onClick={undo}
          disabled={history.length === 0}
        >
          Undo ({history.length})
        </button>
        <button
          type="button"
          className="ucs-panel-button"
          onClick={() => {
            setHistory(past => [...past, view]);
            setView(CANVAS);
          }}
        >
          Reset
        </button>
      </div>
      <p className="proposals-editor-scale">
        {(CANVAS.width / view.width).toFixed(2)}&times; the committed size
      </p>
    </div>
  );

  return {view, overlay, panel};
}
