import {useMemo} from 'react';
import {ArrowMarker} from './arrow_marker';
import {
  isDirected,
  leadsFrom,
  nodeById,
  nodes,
  type ClusterId,
  type Edge,
  type EdgeKind,
  type ProposalNode,
} from './proposals_data';
import {LABEL_WRAP_CHARS, type Layout} from './proposals_layout';
import {neighborsOf} from './proposals_relations';

/**
 * Splits a label across at most two lines, breaking at the space nearest the
 * middle. SVG text does not wrap, so the break is computed rather than left
 * to the renderer.
 */
function labelLines(label: string): string[] {
  if (label.length <= LABEL_WRAP_CHARS) return [label];
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

// Labels never change, so every node's wrapping is computed once here
// rather than on each render.
const LABEL_LINES: Record<string, string[]> = Object.fromEntries(
  nodes.map(node => [node.id, labelLines(node.label)]),
);

// The highlight inputs shared by the node and edge layers: the focused node
// (hover wins over selection), its neighborhood, and the standing legend
// filters.
interface HighlightState {
  focusId: string | null;
  lit: Set<string> | null;
  clusterFilter: boolean;
  selectedClusters: Set<ClusterId>;
}

function inSelectedCluster(state: HighlightState, id: string): boolean {
  const node = nodeById.get(id);
  return node ? state.selectedClusters.has(node.cluster) : false;
}

// Hovering takes precedence over the category legend: one is a momentary
// question about a single node, the other a standing filter.
function nodeStateClass(node: ProposalNode, state: HighlightState): string {
  if (state.focusId) {
    if (node.id === state.focusId) return ' is-focus';
    return state.lit?.has(node.id) ? ' is-linked' : ' is-dim';
  }
  if (state.clusterFilter && !state.selectedClusters.has(node.cluster)) {
    return ' is-dim';
  }
  return '';
}

// Only what the focused node leads to: an incoming arrow is a statement
// about its source, not about the node being read. The cluster test only
// matters with no focus and a filter on.
function edgeStateClass(edge: Edge, state: HighlightState): string {
  if (state.focusId) {
    return leadsFrom(edge, state.focusId) ? ' is-lit' : ' is-dim';
  }
  if (
    state.clusterFilter &&
    !inSelectedCluster(state, edge.from) &&
    !inSelectedCluster(state, edge.to)
  ) {
    return ' is-dim';
  }
  return '';
}

function GraphHulls({layout}: {layout: Layout}) {
  return (
    <g className="proposals-hulls">
      {layout.hulls.map(({id, label, bounds}) => (
        <g
          key={id}
          className={`proposals-hull is-${id}`}
          transform={`translate(${bounds.x}, ${bounds.y})`}
        >
          <rect
            width={bounds.width}
            height={bounds.height}
            rx={26 * layout.scale}
          />
          <text
            x={18 * layout.scale}
            y={25 * layout.scale}
            className="proposals-hull-label"
          >
            {label}
          </text>
        </g>
      ))}
    </g>
  );
}

function GraphEdges({
  layout,
  selectedKinds,
  state,
}: {
  layout: Layout;
  selectedKinds: Set<EdgeKind>;
  state: HighlightState;
}) {
  const kindFilter = selectedKinds.size > 0;
  return (
    <g className="proposals-edges">
      {layout.edges.map(({edge, path}, index) => {
        // The relationship legend hides; the category legend only dims,
        // since hiding an edge whose endpoints are still drawn would read
        // as the relationship not existing.
        if (kindFilter && !selectedKinds.has(edge.kind)) return null;
        const directed = isDirected(edge.kind);
        return (
          <path
            // Node pairs can carry more than one edge, so the index is
            // part of the key.
            key={`${edge.from}-${edge.to}-${edge.kind}-${index}`}
            className={
              `proposals-edge is-${edge.kind}` + edgeStateClass(edge, state)
            }
            d={path}
            markerEnd={directed ? 'url(#proposal-arrow)' : undefined}
          />
        );
      })}
    </g>
  );
}

function NodeLabel({node, layout}: {node: ProposalNode; layout: Layout}) {
  const lines = LABEL_LINES[node.id];
  return (
    <text textAnchor="middle" y={(lines.length === 1 ? 5 : -4) * layout.scale}>
      {lines.map((line, lineIndex) => (
        <tspan key={line} x={0} dy={lineIndex === 0 ? 0 : 17 * layout.scale}>
          {line}
        </tspan>
      ))}
    </text>
  );
}

interface GraphNodeProps {
  node: ProposalNode;
  layout: Layout;
  state: HighlightState;
  selected: boolean;
  onActivate: (id: string | null) => void;
  onSelect: (id: string) => void;
}

function GraphNode(props: GraphNodeProps) {
  const {node, layout, state, selected, onActivate, onSelect} = props;
  const position = layout.positions[node.id];
  return (
    <g
      className={
        `proposals-node is-${node.cluster}${nodeStateClass(node, state)}` +
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
        x={-layout.node.width / 2}
        y={-layout.node.height / 2}
        width={layout.node.width}
        height={layout.node.height}
        rx={12 * layout.scale}
      />
      <NodeLabel node={node} layout={layout} />
    </g>
  );
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
 * @param props.layout Geometry for the space the graph was given.
 */
interface ProposalsGraphProps {
  /** Node being hovered or focused; its relationships are isolated and
   * everything unconnected recedes. */
  activeId: string | null;
  /** Node whose detail is open. */
  selectedId: string | null;
  /** Highlighted edge kinds; empty means all. */
  selectedKinds: Set<EdgeKind>;
  /** Highlighted categories; empty means all. */
  selectedClusters: Set<ClusterId>;
  /** Hover/focus a node, or null on leave. */
  onActivate: (id: string | null) => void;
  /** Open a node's detail. */
  onSelect: (id: string) => void;
  /** Geometry for the space the graph was given. */
  layout: Layout;
}

// The svg defs: userSpaceOnUse rather than the default strokeWidth units —
// the arrowhead should track the drawing's scale, not the line's weight, so
// highlighting an edge thickens it without inflating its head.
function GraphDefs({layout}: {layout: Layout}) {
  return (
    <defs>
      <ArrowMarker
        id="proposal-arrow"
        size={13 * layout.scale}
        units="userSpaceOnUse"
      />
    </defs>
  );
}

function GraphNodes(props: ProposalsGraphProps & {state: HighlightState}) {
  return (
    <g className="proposals-nodes">
      {nodes.map(node => (
        <GraphNode
          key={node.id}
          node={node}
          layout={props.layout}
          state={props.state}
          selected={node.id === props.selectedId}
          onActivate={props.onActivate}
          onSelect={props.onSelect}
        />
      ))}
    </g>
  );
}

export function ProposalsGraph(props: ProposalsGraphProps) {
  const {selectedId, layout} = props;
  // The node driving isolation: an explicit hover wins, otherwise the open
  // selection keeps its relationships lit so the detail panel and the graph
  // agree about what is being discussed.
  const focusId = props.activeId ?? selectedId;
  const lit = useMemo(() => (focusId ? neighborsOf(focusId) : null), [focusId]);

  // An empty legend selection is not a filter: it means nothing has been
  // picked out, so everything stays at full strength.
  const state: HighlightState = {
    focusId,
    lit,
    clusterFilter: props.selectedClusters.size > 0,
    selectedClusters: props.selectedClusters,
  };

  return (
    <svg
      className="proposals-graph"
      width={layout.width}
      height={layout.height}
      role="img"
      aria-label={
        'Relationship graph of the proposals. Each proposal is a focusable ' +
        'button that opens its detail panel.'
      }
    >
      <GraphDefs layout={layout} />
      <GraphHulls layout={layout} />
      <GraphEdges
        layout={layout}
        selectedKinds={props.selectedKinds}
        state={state}
      />
      <GraphNodes {...props} state={state} />
    </svg>
  );
}
