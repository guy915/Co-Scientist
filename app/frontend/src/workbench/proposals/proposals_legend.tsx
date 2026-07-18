import {
  EDGE_KINDS,
  clusters,
  type ClusterId,
  type EdgeKind,
} from './proposals_data';

// A short sample of each edge's stroke, drawn with the same classes the
// graph uses so the legend cannot drift from what it explains.
function EdgeSample({kind}: {kind: EdgeKind}) {
  const directed = kind === 'enables' || kind === 'compensates';
  return (
    <svg
      className="proposals-legend-sample"
      viewBox="0 0 44 12"
      aria-hidden="true"
    >
      <defs>
        <marker
          id={`legend-arrow-${kind}`}
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
      <path
        className={`proposals-edge is-${kind}`}
        d="M 2 6 L 36 6"
        markerEnd={directed ? `url(#legend-arrow-${kind})` : undefined}
      />
    </svg>
  );
}

/**
 * The graph's two legends, overlaid in the top corners. Every entry is a
 * chip that toggles: selecting none is the same as selecting all, so there
 * is no separate reset.
 *
 * @param props.selectedKinds Highlighted edge kinds; empty means all.
 * @param props.onToggleKind Add or remove one edge kind.
 * @param props.selectedClusters Highlighted categories; empty means all.
 * @param props.onToggleCluster Add or remove one category.
 */
export function ProposalsLegend({
  selectedKinds,
  onToggleKind,
  selectedClusters,
  onToggleCluster,
}: {
  selectedKinds: Set<EdgeKind>;
  onToggleKind: (kind: EdgeKind) => void;
  selectedClusters: Set<ClusterId>;
  onToggleCluster: (cluster: ClusterId) => void;
}) {
  return (
    <>
      <div className="proposals-legend is-categories">
        <h2 className="proposals-legend-title">Categories</h2>
        <ul className="proposals-legend-list">
          {clusters.map(cluster => {
            const on = selectedClusters.has(cluster.id);
            return (
              <li key={cluster.id}>
                <button
                  type="button"
                  className={
                    on
                      ? `proposals-chip is-${cluster.id} is-on`
                      : `proposals-chip is-${cluster.id}`
                  }
                  aria-pressed={on}
                  onClick={() => onToggleCluster(cluster.id)}
                >
                  <span
                    className="proposals-legend-swatch"
                    aria-hidden="true"
                  />
                  <span>{cluster.label}</span>
                </button>
              </li>
            );
          })}
        </ul>
      </div>

      <div className="proposals-legend is-relationships">
        <h2 className="proposals-legend-title">Relationships</h2>
        <ul className="proposals-legend-list">
          {EDGE_KINDS.map(({kind, label}) => {
            const on = selectedKinds.has(kind);
            return (
              <li key={kind}>
                <button
                  type="button"
                  className={
                    on
                      ? `proposals-chip is-${kind} is-on`
                      : `proposals-chip is-${kind}`
                  }
                  aria-pressed={on}
                  onClick={() => onToggleKind(kind)}
                >
                  <EdgeSample kind={kind} />
                  <span>{label}</span>
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </>
  );
}
