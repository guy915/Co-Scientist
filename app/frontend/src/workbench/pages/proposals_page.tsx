import {useCallback, useMemo, useState, type CSSProperties} from 'react';
import {useSearchParams} from 'react-router-dom';
import {
  nodeById,
  type ClusterId,
  type EdgeKind,
  type ProposalNode,
} from '../proposals/proposals_data';
import {ProposalsDetail} from '../proposals/proposals_detail';
import {ProposalsGraph} from '../proposals/proposals_graph';
import {ProposalsLegend} from '../proposals/proposals_legend';
import {
  LEGEND_WIDTH,
  computeLayout,
  type Layout,
} from '../proposals/proposals_layout';
import {useStage} from '../proposals/use_stage';

// Adds or removes one member, which is all either legend needs: an empty
// set means "no filter", so unselecting the last chip restores the graph
// without a separate reset control.
function toggled<T>(current: Set<T>, value: T): Set<T> {
  const next = new Set(current);
  if (next.has(value)) next.delete(value);
  else next.add(value);
  return next;
}

// The two legend filters (relationship kinds and categories) plus their
// toggle handlers.
function useLegendFilters() {
  const [selectedKinds, setSelectedKinds] = useState<Set<EdgeKind>>(new Set());
  const [selectedClusters, setSelectedClusters] = useState<Set<ClusterId>>(
    new Set(),
  );
  const toggleKind = useCallback(
    (kind: EdgeKind) => setSelectedKinds(current => toggled(current, kind)),
    [],
  );
  const toggleCluster = useCallback(
    (cluster: ClusterId) =>
      setSelectedClusters(current => toggled(current, cluster)),
    [],
  );
  return {selectedKinds, selectedClusters, toggleKind, toggleCluster};
}

// Selection lives in the query string so a particular proposal can be
// linked to and shared. The panel slides out rather than vanishing, so the
// node stays rendered until the animation finishes; `leaving` holds it
// there in the meantime.
function useProposalSelection() {
  const [params, setParams] = useSearchParams();
  const [leaving, setLeaving] = useState<ProposalNode | null>(null);

  const selectedId = params.get('node');
  const selected = useMemo(
    () => (selectedId ? (nodeById.get(selectedId) ?? null) : null),
    [selectedId],
  );

  const select = useCallback(
    (id: string) => {
      // `replace` keeps the back button meaningful: walking the argument
      // node to node should not fill history with every hop. Choosing the
      // open node again closes it, so the same gesture opens and dismisses.
      // Every caller passes a real node id, so only the toggle is checked.
      if (id === selectedId) setLeaving(selected);
      setParams(id !== selectedId ? {node: id} : {}, {replace: true});
    },
    [setParams, selectedId, selected],
  );

  const clearSelection = useCallback(() => {
    if (selected) setLeaving(selected);
    setParams({}, {replace: true});
  }, [setParams, selected]);

  const clearLeaving = useCallback(() => setLeaving(null), []);

  return {
    selectedId,
    selected,
    shown: selected ?? leaving,
    select,
    clearSelection,
    clearLeaving,
  };
}

// The stage's CSS custom properties: the legend cards take their width from
// the same constant the layout reserves for them, so the two cannot drift
// apart.
function stageStyle(layout: Layout): CSSProperties {
  return {
    '--proposals-scale': layout.scale,
    '--proposals-legend-width': `${LEGEND_WIDTH}px`,
  } as CSSProperties;
}

interface ProposalsStageProps {
  activeId: string | null;
  onActivate: (id: string | null) => void;
  filters: ReturnType<typeof useLegendFilters>;
  selection: ReturnType<typeof useProposalSelection>;
}

// The stage is what gets measured: the graph fills it exactly, and the
// legends are positioned in its corners. The graph is laid out into the
// space it is actually given, in real pixels, so the measurement has to
// come first and the geometry second.
function ProposalsStage(props: ProposalsStageProps) {
  const {filters, selection} = props;
  const [stageRef, stage] = useStage();
  const layout = useMemo(() => computeLayout(stage), [stage]);
  return (
    <div className="proposals-stage" ref={stageRef} style={stageStyle(layout)}>
      <ProposalsGraph
        activeId={props.activeId}
        selectedId={selection.selectedId}
        selectedKinds={filters.selectedKinds}
        selectedClusters={filters.selectedClusters}
        onActivate={props.onActivate}
        onSelect={selection.select}
        layout={layout}
      />
      {/* The legends explain the whole graph; while one proposal is open
          the detail panel is the thing being read, so they step aside. */}
      {!selection.selected && (
        <ProposalsLegend
          selectedKinds={filters.selectedKinds}
          onToggleKind={filters.toggleKind}
          selectedClusters={filters.selectedClusters}
          onToggleCluster={filters.toggleCluster}
        />
      )}
    </div>
  );
}

/**
 * The proposals relationship graph, sized to fill the viewport. The graph is
 * the whole page: the two legends explain and filter it, and the detail
 * panel reads one proposal at a time.
 */
export function ProposalsPage() {
  const [activeId, setActiveId] = useState<string | null>(null);
  const filters = useLegendFilters();
  const selection = useProposalSelection();

  return (
    <div className="proposals-page">
      <ProposalsStage
        activeId={activeId}
        onActivate={setActiveId}
        filters={filters}
        selection={selection}
      />
      {selection.shown && (
        <ProposalsDetail
          key={selection.shown.id}
          node={selection.shown}
          leaving={selection.selected === null}
          onSelect={selection.select}
          onClose={selection.clearSelection}
          onLeft={selection.clearLeaving}
        />
      )}
    </div>
  );
}
