import {useMemo} from 'react';
import {
  clusters,
  leadsFrom,
  nodes,
  type ClusterId,
  type EdgeKind,
  type ProposalNode,
} from './proposals_data';
import {
  CANVAS,
  NODE,
  clusterBounds,
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

/**
 * The relationship graph.
 *
 * @param props.activeId Node being hovered or focused; its relationships are
 *   isolated and everything unconnected recedes.
 * @param props.selectedId Node whose detail is open.
 * @param props.selectedKinds Highlighted edge kinds; empty means all.
 * @param props.selectedClusters Highlighted categories; empty means all.
 * @param props.onActivate Hover/focus a node, or null on leave.
 * @param props.onSelect Open a node's detail.
 */
export function ProposalsGraph({
  activeId,
  selectedId,
  selectedKinds,
  selectedClusters,
  onActivate,
  onSelect,
}: {
  activeId: string | null;
  selectedId: string | null;
  selectedKinds: Set<EdgeKind>;
  selectedClusters: Set<ClusterId>;
  onActivate: (id: string | null) => void;
  onSelect: (id: string) => void;
}) {
  // The node driving isolation: an explicit hover wins, otherwise the open
  // selection keeps its relationships lit so the detail panel and the graph
  // agree about what is being discussed.
  const focusId = activeId ?? selectedId;
  const lit = useMemo(() => (focusId ? neighborsOf(focusId) : null), [focusId]);

  // An empty legend selection is not a filter: it means nothing has been
  // picked out, so everything stays at full strength.
  const clusterFilter = selectedClusters.size > 0;
  const kindFilter = selectedKinds.size > 0;

  function inSelectedCluster(id: string): boolean {
    const node = nodes.find(entry => entry.id === id);
    return node ? selectedClusters.has(node.cluster) : false;
  }

  // Hovering takes precedence over the category legend: one is a momentary
  // question about a single node, the other a standing filter.
  function nodeState(node: ProposalNode): string {
    if (focusId) {
      if (node.id === focusId) return ' is-focus';
      return lit?.has(node.id) ? ' is-linked' : ' is-dim';
    }
    if (clusterFilter && !selectedClusters.has(node.cluster)) return ' is-dim';
    return '';
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
          // The relationship legend hides; the category legend only dims,
          // since hiding an edge whose endpoints are still drawn would read
          // as the relationship not existing.
          if (kindFilter && !selectedKinds.has(edge.kind)) return null;
          // Only what the focused node leads to: an incoming arrow is a
          // statement about its source, not about the node being read.
          const touchesFocus = focusId !== null && leadsFrom(edge, focusId);
          const touchesCluster =
            inSelectedCluster(edge.from) || inSelectedCluster(edge.to);
          const state = focusId
            ? touchesFocus
              ? ' is-lit'
              : ' is-dim'
            : clusterFilter && !touchesCluster
              ? ' is-dim'
              : '';
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
