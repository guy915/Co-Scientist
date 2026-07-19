import {useCallback, useMemo, useState, type CSSProperties} from 'react';
import {useSearchParams} from 'react-router-dom';
import {
  nodes,
  type ClusterId,
  type EdgeKind,
  type ProposalNode,
} from '../proposals/proposals_data';
import {ProposalsDetail} from '../proposals/proposals_detail';
import {ProposalsGraph} from '../proposals/proposals_graph';
import {ProposalsLegend} from '../proposals/proposals_legend';
import {computeLayout} from '../proposals/proposals_layout';
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

/**
 * The proposals relationship graph, sized to fill the viewport. The graph is
 * the whole page: the two legends explain and filter it, and the detail
 * panel reads one proposal at a time. Selection lives in the query string so
 * a particular proposal can be linked to and shared.
 */
export function ProposalsPage() {
  const [params, setParams] = useSearchParams();
  const [activeId, setActiveId] = useState<string | null>(null);
  const [selectedKinds, setSelectedKinds] = useState<Set<EdgeKind>>(new Set());
  const [selectedClusters, setSelectedClusters] = useState<Set<ClusterId>>(
    new Set(),
  );

  // The panel slides out rather than vanishing, so the node stays rendered
  // until the animation finishes. `leaving` holds it there in the meantime.
  const [leaving, setLeaving] = useState<ProposalNode | null>(null);

  const selectedId = params.get('node');
  const selected = useMemo(
    () => nodes.find(node => node.id === selectedId) ?? null,
    [selectedId],
  );

  const select = useCallback(
    (id: string) => {
      // `replace` keeps the back button meaningful: walking the argument
      // node to node should not fill history with every hop. Choosing the
      // open node again closes it, so the same gesture opens and dismisses.
      if (id === selectedId) setLeaving(selected);
      setParams(id && id !== selectedId ? {node: id} : {}, {replace: true});
    },
    [setParams, selectedId, selected],
  );

  const clearSelection = useCallback(() => {
    if (selected) setLeaving(selected);
    setParams({}, {replace: true});
  }, [setParams, selected]);

  const shown = selected ?? leaving;

  // The graph is laid out into the space it is actually given, in real
  // pixels, so the measurement has to come first and the geometry second.
  const [stageRef, stage] = useStage();
  const layout = useMemo(() => computeLayout(stage), [stage]);

  return (
    <div className="proposals-page">
      {/* The stage is what gets measured: the graph fills it exactly, and
          the legends are positioned in its corners. */}
      <div
        className="proposals-stage"
        ref={stageRef}
        style={{'--proposals-scale': layout.scale} as CSSProperties}
      >
        <ProposalsGraph
          activeId={activeId}
          selectedId={selectedId}
          selectedKinds={selectedKinds}
          selectedClusters={selectedClusters}
          onActivate={setActiveId}
          onSelect={select}
          layout={layout}
        />
        {/* The legends explain the whole graph; while one proposal is open
            the detail panel is the thing being read, so they step aside. */}
        {!selected && (
          <ProposalsLegend
            selectedKinds={selectedKinds}
            onToggleKind={kind =>
              setSelectedKinds(current => toggled(current, kind))
            }
            selectedClusters={selectedClusters}
            onToggleCluster={cluster =>
              setSelectedClusters(current => toggled(current, cluster))
            }
          />
        )}
      </div>
      {shown && (
        <ProposalsDetail
          key={shown.id}
          node={shown}
          leaving={selected === null}
          onSelect={select}
          onClose={clearSelection}
          onLeft={() => setLeaving(null)}
        />
      )}
    </div>
  );
}
