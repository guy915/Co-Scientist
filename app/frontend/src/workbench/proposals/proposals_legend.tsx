import {EDGE_KINDS, clusters, type EdgeKind} from './proposals_data';

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
 * The graph's two legends, overlaid in the top corners: groups (node hue) on
 * the left, relationships (edge color and stroke) on the right. Names only —
 * the detail panel carries the explanations. The relationship entries double
 * as the edge filter.
 *
 * @param props.visibleKinds Edge kinds currently shown.
 * @param props.onToggleKind Flip one kind on or off.
 * @param props.onOnlyKind Show a single kind, for one-click access to just
 *   the tensions.
 * @param props.onReset Restore every kind.
 */
export function ProposalsLegend({
  visibleKinds,
  onToggleKind,
  onOnlyKind,
  onReset,
}: {
  visibleKinds: Set<EdgeKind>;
  onToggleKind: (kind: EdgeKind) => void;
  onOnlyKind: (kind: EdgeKind) => void;
  onReset: () => void;
}) {
  const allVisible = visibleKinds.size === EDGE_KINDS.length;
  return (
    <>
      <div className="proposals-legend is-groups">
        <h2 className="proposals-legend-title">Groups</h2>
        <ul className="proposals-legend-list">
          {clusters.map(cluster => (
            <li key={cluster.id} className="proposals-legend-item">
              <span
                className={`proposals-legend-swatch is-${cluster.id}`}
                aria-hidden="true"
              />
              <span>{cluster.label}</span>
            </li>
          ))}
        </ul>
      </div>

      <div className="proposals-legend is-relationships">
        <h2 className="proposals-legend-title">Relationships</h2>
        <ul className="proposals-legend-list">
          {EDGE_KINDS.map(({kind, label}) => {
            const on = visibleKinds.has(kind);
            return (
              <li key={kind} className="proposals-legend-item">
                <button
                  type="button"
                  className={
                    on ? 'proposals-filter' : 'proposals-filter is-off'
                  }
                  aria-pressed={on}
                  // Click isolates one kind; that is the common intent and
                  // takes a single click. Shift-click adds or removes one
                  // kind without disturbing the rest.
                  onClick={event => {
                    if (event.shiftKey) onToggleKind(kind);
                    else onOnlyKind(kind);
                  }}
                >
                  <EdgeSample kind={kind} />
                  <span>{label}</span>
                </button>
              </li>
            );
          })}
        </ul>
        {!allVisible && (
          <button type="button" className="proposals-reset" onClick={onReset}>
            Show all
          </button>
        )}
      </div>
    </>
  );
}
