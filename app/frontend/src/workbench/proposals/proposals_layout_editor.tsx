// TEMPORARY: a layout editor for /proposals, reached with ?edit=1.
//
// It exists to settle the cluster arrangement by dragging rather than by
// guessing coordinates. Drag a cluster to move it, drag its bottom-right
// handle to resize its ring, then copy the printed ring table into
// proposals_layout.ts. Once the layout is committed this file and its two
// call sites in proposals_page.tsx should be deleted.

import {useCallback, useRef, useState} from 'react';
import {clusters, type ClusterId} from './proposals_data';
import {
  RINGS,
  clusterBoundsFor,
  type Point,
  type Rings,
} from './proposals_layout';

/** Rings are cloned so editing never mutates the committed table. */
function cloneRings(rings: Rings): Rings {
  return Object.fromEntries(
    Object.entries(rings).map(([id, ring]) => [
      id,
      {...ring, center: {...ring.center}},
    ]),
  ) as Rings;
}

/** The ring table, formatted to paste straight into proposals_layout.ts. */
function printRings(rings: Rings): string {
  const lines = clusters.map(cluster => {
    const ring = rings[cluster.id];
    const round = (value: number) => Math.round(value);
    return (
      `  ${cluster.id}: {center: {x: ${round(ring.center.x)}, ` +
      `y: ${round(ring.center.y)}}, rx: ${round(ring.rx)}, ` +
      `ry: ${round(ring.ry)}, start: ${ring.start}},`
    );
  });
  return `const RINGS: Rings = {\n${lines.join('\n')}\n};`;
}

type Drag =
  | {kind: 'move'; cluster: ClusterId; from: Point; center: Point}
  | {kind: 'resize'; cluster: ClusterId; from: Point; rx: number; ry: number};

/**
 * Editing state and the handles drawn over the graph.
 *
 * @returns The live ring table, the SVG overlay, and the readout panel.
 */
export function useLayoutEditor() {
  const [rings, setRings] = useState<Rings>(() => cloneRings(RINGS));
  const drag = useRef<Drag | null>(null);

  // Pointer coordinates arrive in screen space; every ring value is in canvas
  // space, so each event is mapped through the SVG's inverse matrix.
  const toCanvas = useCallback(
    (event: React.PointerEvent<SVGElement>): Point => {
      const svg = event.currentTarget.ownerSVGElement;
      if (!svg) return {x: 0, y: 0};
      const point = svg.createSVGPoint();
      point.x = event.clientX;
      point.y = event.clientY;
      const matrix = svg.getScreenCTM();
      if (!matrix) return {x: 0, y: 0};
      const mapped = point.matrixTransform(matrix.inverse());
      return {x: mapped.x, y: mapped.y};
    },
    [],
  );

  const onPointerMove = useCallback(
    (event: React.PointerEvent<SVGElement>) => {
      const active = drag.current;
      if (!active) return;
      const at = toCanvas(event);
      const dx = at.x - active.from.x;
      const dy = at.y - active.from.y;
      setRings(current => {
        const next = cloneRings(current);
        const ring = next[active.cluster];
        if (active.kind === 'move') {
          ring.center = {x: active.center.x + dx, y: active.center.y + dy};
        } else {
          ring.rx = Math.max(0, active.rx + dx);
          ring.ry = Math.max(20, active.ry + dy);
        }
        return next;
      });
    },
    [toCanvas],
  );

  const endDrag = useCallback((event: React.PointerEvent<SVGElement>) => {
    drag.current = null;
    event.currentTarget.releasePointerCapture(event.pointerId);
  }, []);

  const overlay = useCallback(
    (positions: Record<string, Point>) => (
      <g className="proposals-editor">
        {clusters.map(cluster => {
          const bounds = clusterBoundsFor(rings, positions, cluster.id);
          const ring = rings[cluster.id];
          return (
            <g key={cluster.id}>
              {/* The whole box moves the cluster. */}
              <rect
                className="proposals-editor-move"
                x={bounds.x}
                y={bounds.y}
                width={bounds.width}
                height={bounds.height}
                rx={28}
                onPointerDown={event => {
                  event.currentTarget.setPointerCapture(event.pointerId);
                  drag.current = {
                    kind: 'move',
                    cluster: cluster.id,
                    from: toCanvas(event),
                    center: {...ring.center},
                  };
                }}
                onPointerMove={onPointerMove}
                onPointerUp={endDrag}
              />
              {/* The corner grows or shrinks the ring the nodes sit on. */}
              <rect
                className="proposals-editor-resize"
                x={bounds.x + bounds.width - 20}
                y={bounds.y + bounds.height - 20}
                width={18}
                height={18}
                rx={4}
                onPointerDown={event => {
                  event.currentTarget.setPointerCapture(event.pointerId);
                  drag.current = {
                    kind: 'resize',
                    cluster: cluster.id,
                    from: toCanvas(event),
                    rx: ring.rx,
                    ry: ring.ry,
                  };
                }}
                onPointerMove={onPointerMove}
                onPointerUp={endDrag}
              />
            </g>
          );
        })}
      </g>
    ),
    [rings, toCanvas, onPointerMove, endDrag],
  );

  const panel = (
    <div className="proposals-editor-panel">
      <p>
        Drag a cluster to move it; drag its bottom-right square to resize. When
        it looks right, copy this and paste it into proposals_layout.ts.
      </p>
      <textarea readOnly rows={9} value={printRings(rings)} />
      <button
        type="button"
        className="ucs-panel-button"
        onClick={() => setRings(cloneRings(RINGS))}
      >
        Reset
      </button>
    </div>
  );

  return {rings, overlay, panel};
}
