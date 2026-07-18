// TEMPORARY: a layout editor for /proposals, reached with ?edit=1.
//
// It exists to settle the cluster arrangement by dragging rather than by
// guessing coordinates. Drag a cluster to move it, drag any bottom-right
// handle to resize every cluster at once, then copy the printed ring table
// into proposals_layout.ts. Once the layout is committed this file and its
// two call sites in proposals_page.tsx should be deleted.

import {useCallback, useEffect, useRef, useState} from 'react';
import {clusters, type ClusterId} from './proposals_data';
import {
  RINGS,
  clusterBoundsFor,
  type Point,
  type Rings,
} from './proposals_layout';

/**
 * What the editor actually varies: where each cluster sits, and one scale
 * shared by all of them. Ring radii are never edited per cluster — the
 * clusters are meant to stay uniform, so resizing is a single number.
 */
interface Draft {
  centers: Record<ClusterId, Point>;
  scale: number;
}

const INITIAL: Draft = {
  centers: Object.fromEntries(
    clusters.map(cluster => [cluster.id, {...RINGS[cluster.id].center}]),
  ) as Record<ClusterId, Point>,
  scale: 1,
};

/** The committed radii, which the shared scale multiplies. */
function ringsFor(draft: Draft): Rings {
  return Object.fromEntries(
    clusters.map(cluster => {
      const base = RINGS[cluster.id];
      return [
        cluster.id,
        {
          center: draft.centers[cluster.id],
          rx: base.rx * draft.scale,
          ry: base.ry * draft.scale,
          start: base.start,
        },
      ];
    }),
  ) as Rings;
}

/** The ring table, formatted to paste straight into proposals_layout.ts. */
function printRings(rings: Rings): string {
  const lines = clusters.map(cluster => {
    const ring = rings[cluster.id];
    const round = Math.round;
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
  | {kind: 'resize'; from: Point; scale: number; unit: number};

/**
 * Editing state and the handles drawn over the graph.
 *
 * @returns The live ring table, the SVG overlay, and the readout panel.
 */
export function useLayoutEditor() {
  const [draft, setDraft] = useState<Draft>(INITIAL);
  // Every gesture pushes the state it started from, so undo steps back one
  // drag rather than one pointer sample.
  const [history, setHistory] = useState<Draft[]>([]);
  const drag = useRef<Drag | null>(null);

  const undo = useCallback(() => {
    setHistory(past => {
      if (past.length === 0) return past;
      setDraft(past[past.length - 1]);
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

  const beginDrag = useCallback((next: Drag, current: Draft) => {
    setHistory(past => [...past, current]);
    drag.current = next;
  }, []);

  const onPointerMove = useCallback(
    (event: React.PointerEvent<SVGElement>) => {
      const active = drag.current;
      if (!active) return;
      const at = toCanvas(event);
      const dx = at.x - active.from.x;
      const dy = at.y - active.from.y;
      setDraft(current => {
        if (active.kind === 'move') {
          return {
            ...current,
            centers: {
              ...current.centers,
              [active.cluster]: {
                x: active.center.x + dx,
                y: active.center.y + dy,
              },
            },
          };
        }
        // Dragging the corner outward grows every cluster together. The
        // handle's own distance from its cluster center sets the unit, so
        // the box tracks the pointer at roughly 1:1.
        const scale = active.scale + (dx + dy) / (2 * active.unit);
        return {...current, scale: Math.min(3, Math.max(0.35, scale))};
      });
    },
    [toCanvas],
  );

  const endDrag = useCallback((event: React.PointerEvent<SVGElement>) => {
    drag.current = null;
    event.currentTarget.releasePointerCapture(event.pointerId);
  }, []);

  const rings = ringsFor(draft);

  const overlay = useCallback(
    (positions: Record<string, Point>) => (
      <g className="proposals-editor">
        {clusters.map(cluster => {
          const bounds = clusterBoundsFor(rings, positions, cluster.id);
          const center = draft.centers[cluster.id];
          return (
            <g key={cluster.id}>
              {/* The whole box moves this cluster. */}
              <rect
                className="proposals-editor-move"
                x={bounds.x}
                y={bounds.y}
                width={bounds.width}
                height={bounds.height}
                rx={28}
                onPointerDown={event => {
                  event.currentTarget.setPointerCapture(event.pointerId);
                  beginDrag(
                    {
                      kind: 'move',
                      cluster: cluster.id,
                      from: toCanvas(event),
                      center: {...center},
                    },
                    draft,
                  );
                }}
                onPointerMove={onPointerMove}
                onPointerUp={endDrag}
              />
              {/* Any corner resizes every cluster: the scale is shared. */}
              <rect
                className="proposals-editor-resize"
                x={bounds.x + bounds.width - 20}
                y={bounds.y + bounds.height - 20}
                width={18}
                height={18}
                rx={4}
                onPointerDown={event => {
                  event.currentTarget.setPointerCapture(event.pointerId);
                  const corner = {
                    x: bounds.x + bounds.width,
                    y: bounds.y + bounds.height,
                  };
                  beginDrag(
                    {
                      kind: 'resize',
                      from: toCanvas(event),
                      scale: draft.scale,
                      unit:
                        (Math.abs(corner.x - center.x) +
                          Math.abs(corner.y - center.y)) /
                          2 || 100,
                    },
                    draft,
                  );
                }}
                onPointerMove={onPointerMove}
                onPointerUp={endDrag}
              />
            </g>
          );
        })}
      </g>
    ),
    [rings, draft, toCanvas, beginDrag, onPointerMove, endDrag],
  );

  const panel = (
    <div className="proposals-editor-panel">
      <p>
        Drag a cluster to move it. Drag any bottom-right square to resize them
        all — the scale is shared. Ctrl/Cmd+Z undoes. When it looks right, copy
        this into proposals_layout.ts.
      </p>
      <textarea readOnly rows={9} value={printRings(rings)} />
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
            setHistory(past => [...past, draft]);
            setDraft(INITIAL);
          }}
        >
          Reset
        </button>
      </div>
      <p className="proposals-editor-scale">
        Scale {draft.scale.toFixed(2)}&times;
      </p>
    </div>
  );

  return {rings, overlay, panel};
}
