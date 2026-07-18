import {useCallback, useMemo, useState} from 'react';
import {useSearchParams} from 'react-router-dom';
import {
  nodes,
  type ClusterId,
  type EdgeKind,
} from '../proposals/proposals_data';
import {ProposalsDetail} from '../proposals/proposals_detail';
import {ProposalsGraph} from '../proposals/proposals_graph';
import {ProposalsLegend} from '../proposals/proposals_legend';
// TEMPORARY: delete along with proposals_layout_editor.tsx once the cluster
// arrangement is settled.
import {useLayoutEditor} from '../proposals/proposals_layout_editor';

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

  const editing = params.get('edit') === '1';
  const editor = useLayoutEditor();

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
      setParams(id && id !== selectedId ? {node: id} : {}, {replace: true});
    },
    [setParams, selectedId],
  );

  const clearSelection = useCallback(() => {
    setParams({}, {replace: true});
  }, [setParams]);

  return (
    <div className="proposals-page">
      {/* The stage carries no styling of its own — it exists only as the
          positioning context the corner legends anchor to. */}
      <div className="proposals-stage">
        <ProposalsGraph
          activeId={activeId}
          selectedId={selectedId}
          selectedKinds={selectedKinds}
          selectedClusters={selectedClusters}
          onActivate={setActiveId}
          onSelect={select}
          rings={editing ? editor.rings : undefined}
          overlay={editing ? editor.overlay : undefined}
        />
        {/* The legends explain the whole graph; while one proposal is open
            the detail panel is the thing being read, so they step aside. */}
        {editing && editor.panel}
        {!selected && !editing && (
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
      {selected && (
        <ProposalsDetail
          node={selected}
          onSelect={select}
          onClose={clearSelection}
        />
      )}
    </div>
  );
}
