import {useCallback, useMemo, useState} from 'react';
import {useSearchParams} from 'react-router-dom';
import {EDGE_KINDS, nodes, type EdgeKind} from '../proposals/proposals_data';
import {ProposalsDetail} from '../proposals/proposals_detail';
import {ProposalsGraph} from '../proposals/proposals_graph';
import {ProposalsLegend} from '../proposals/proposals_legend';

const ALL_KINDS = new Set<EdgeKind>(EDGE_KINDS.map(entry => entry.kind));

/**
 * The proposals relationship graph, sized to fill the viewport. The graph is
 * the whole page: the two legends explain it and the detail panel reads one
 * proposal at a time. Selection lives in the query string so a particular
 * proposal can be linked to and shared.
 */
export function ProposalsPage() {
  const [params, setParams] = useSearchParams();
  const [activeId, setActiveId] = useState<string | null>(null);
  const [visibleKinds, setVisibleKinds] = useState<Set<EdgeKind>>(ALL_KINDS);

  const selectedId = params.get('node');
  const selected = useMemo(
    () => nodes.find(node => node.id === selectedId) ?? null,
    [selectedId],
  );

  const select = useCallback(
    (id: string) => {
      // `replace` keeps the back button meaningful: walking the argument
      // node to node should not fill history with every hop.
      setParams(id ? {node: id} : {}, {replace: true});
    },
    [setParams],
  );

  const clearSelection = useCallback(() => {
    setParams({}, {replace: true});
  }, [setParams]);

  function toggleKind(kind: EdgeKind) {
    setVisibleKinds(current => {
      const next = new Set(current);
      if (next.has(kind)) next.delete(kind);
      else next.add(kind);
      return next;
    });
  }

  function onlyKind(kind: EdgeKind) {
    setVisibleKinds(current =>
      // A second click on an already-isolated kind restores everything, so
      // the filter never becomes a trap.
      current.size === 1 && current.has(kind)
        ? new Set(ALL_KINDS)
        : new Set([kind]),
    );
  }

  return (
    <div className="proposals-page">
      <div className="proposals-canvas">
        <ProposalsGraph
          activeId={activeId}
          selectedId={selectedId}
          visibleKinds={visibleKinds}
          onActivate={setActiveId}
          onSelect={select}
        />
      </div>
      {selected && (
        <ProposalsDetail
          node={selected}
          onSelect={select}
          onClose={clearSelection}
        />
      )}
      <ProposalsLegend
        visibleKinds={visibleKinds}
        onToggleKind={toggleKind}
        onOnlyKind={onlyKind}
        onReset={() => setVisibleKinds(new Set(ALL_KINDS))}
      />
    </div>
  );
}
