import {useMemo} from 'react';
import {
  clusters,
  nodes,
  type EdgeKind,
  type ProposalNode,
} from './proposals_data';
import {
  CANVAS,
  NODE,
  edgeGeometry,
  neighborsOf,
  nodePositions,
} from './proposals_layout';

/**
 * Splits a label across at most two lines, breaking at the space nearest the
 * middle. SVG text does not wrap, so the break is computed rather than left
 * to the renderer.
 */
function labelLines(label: string): string[] {
  if (label.length <= 18) return [label];
  const middle = Math.floor(label.length / 2);
  let breakAt = -1;
  for (let i = 0; i < label.length; i++) {
    if (label[i] !== ' ') continue;
    if (breakAt === -1 || Math.abs(i - middle) < Math.abs(breakAt - middle)) {
      breakAt = i;
    }
  }
  if (breakAt === -1) return [label];
  return [label.slice(0, breakAt), label.slice(breakAt + 1)];
}

// Cluster hulls: a soft rounded rect behind each cluster's nodes, so the
// grouping reads spatially before any label is processed. Sized from the
// ring extents rather than hardcoded.
function clusterBounds(clusterId: string) {
  const members = nodes.filter(node => node.cluster === clusterId);
  const xs = members.map(node => nodePositions[node.id].x);
  const ys = members.map(node => nodePositions[node.id].y);
  const padX = NODE.width / 2 + 26;
  const padY = NODE.height / 2 + 34;
  return {
    x: Math.min(...xs) - padX,
    y: Math.min(...ys) - padY,
    width: Math.max(...xs) - Math.min(...xs) + padX * 2,
    height: Math.max(...ys) - Math.min(...ys) + padY * 2,
  };
}

/**
 * The relationship graph.
 *
 * @param props.activeId Node being hovered or focused; its relationships are
 *   isolated and everything unconnected recedes.
 * @param props.selectedId Node whose detail is open.
 * @param props.visibleKinds Edge kinds currently passing the filter.
 * @param props.onActivate Hover/focus a node, or null on leave.
 * @param props.onSelect Open a node's detail.
 */
export function ProposalsGraph({
  activeId,
  selectedId,
  visibleKinds,
  onActivate,
  onSelect,
}: {
  activeId: string | null;
  selectedId: string | null;
  visibleKinds: Set<EdgeKind>;
  onActivate: (id: string | null) => void;
  onSelect: (id: string) => void;
}) {
  // The node driving isolation: an explicit hover wins, otherwise the open
  // selection keeps its relationships lit so the detail panel and the graph
  // agree about what is being discussed.
  const focusId = activeId ?? selectedId;
  const lit = useMemo(() => (focusId ? neighborsOf(focusId) : null), [focusId]);

  function nodeState(node: ProposalNode): string {
    if (!focusId) return '';
    if (node.id === focusId) return ' is-focus';
    return lit?.has(node.id) ? ' is-linked' : ' is-dim';
  }

  return (
    <svg
      className="proposals-graph"
      viewBox={`0 0 ${CANVAS.width} ${CANVAS.height}`}
      role="img"
      aria-label={
        'Relationship graph of the proposals. The same content is written ' +
        'out in full below.'
      }
    >
      <defs>
        {/* context-stroke keeps the arrowhead the same color as the edge it
            terminates, including while dimmed. */}
        <marker
          id="proposal-arrow"
          viewBox="0 0 10 10"
          refX="9"
          refY="5"
          markerWidth="7"
          markerHeight="7"
          orient="auto-start-reverse"
        >
          <path d="M 0 0 L 10 5 L 0 10 z" fill="context-stroke" />
        </marker>
      </defs>

      <g className="proposals-hulls">
        {clusters.map(cluster => {
          const bounds = clusterBounds(cluster.id);
          return (
            <g key={cluster.id} className={`proposals-hull is-${cluster.id}`}>
              <rect
                x={bounds.x}
                y={bounds.y}
                width={bounds.width}
                height={bounds.height}
                rx={28}
              />
              <text
                x={bounds.x + 16}
                y={bounds.y + 22}
                className="proposals-hull-label"
              >
                {cluster.label}
              </text>
            </g>
          );
        })}
      </g>

      <g className="proposals-edges">
        {edgeGeometry.map(({edge, path}, index) => {
          if (!visibleKinds.has(edge.kind)) return null;
          const touchesFocus =
            focusId !== null && (edge.from === focusId || edge.to === focusId);
          const state =
            focusId === null ? '' : touchesFocus ? ' is-lit' : ' is-dim';
          const directed =
            edge.kind === 'enables' || edge.kind === 'compensates';
          return (
            <path
              // Node pairs can carry more than one edge, so the index is
              // part of the key.
              key={`${edge.from}-${edge.to}-${edge.kind}-${index}`}
              className={`proposals-edge is-${edge.kind}${state}`}
              d={path}
              markerEnd={directed ? 'url(#proposal-arrow)' : undefined}
            />
          );
        })}
      </g>

      <g className="proposals-nodes">
        {nodes.map(node => {
          const position = nodePositions[node.id];
          const lines = labelLines(node.label);
          const selected = node.id === selectedId;
          return (
            <g
              key={node.id}
              className={
                `proposals-node is-${node.cluster}${nodeState(node)}` +
                (selected ? ' is-selected' : '')
              }
              transform={`translate(${position.x}, ${position.y})`}
              role="button"
              tabIndex={0}
              aria-pressed={selected}
              aria-label={`${node.label}. ${node.summary}`}
              onMouseEnter={() => onActivate(node.id)}
              onMouseLeave={() => onActivate(null)}
              // Focus mirrors hover so the keyboard path gets the same
              // isolation behavior as the mouse.
              onFocus={() => onActivate(node.id)}
              onBlur={() => onActivate(null)}
              onClick={() => onSelect(node.id)}
              onKeyDown={event => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault();
                  onSelect(node.id);
                }
              }}
            >
              <rect
                x={-NODE.width / 2}
                y={-NODE.height / 2}
                width={NODE.width}
                height={NODE.height}
                rx={10}
              />
              <text textAnchor="middle" y={lines.length === 1 ? 4 : -3}>
                {lines.map((line, lineIndex) => (
                  <tspan key={line} x={0} dy={lineIndex === 0 ? 0 : 14}>
                    {line}
                  </tspan>
                ))}
              </text>
            </g>
          );
        })}
      </g>
    </svg>
  );
}
