import {useEffect, useState} from 'react';
import {Icon} from '@/components/icon';
import {EDGE_KINDS, clusters, type EdgeKind} from './proposals_data';

// A short sample of each edge's stroke, drawn with the same classes the
// graph uses so the legend cannot drift from what it explains.
function EdgeSample({kind}: {kind: EdgeKind}) {
  const directed = kind === 'enables' || kind === 'compensates';
  return (
    <svg
      className="proposals-legend-sample"
      viewBox="0 0 48 12"
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
        d="M 2 6 L 40 6"
        markerEnd={directed ? `url(#legend-arrow-${kind})` : undefined}
      />
    </svg>
  );
}

type Panel = 'groups' | 'relationships';

// One legend button plus the popover it opens. The popover is a sibling of
// the button inside a positioned wrapper, so it anchors to its own button.
function LegendPopover({
  id,
  label,
  note,
  open,
  onToggle,
  children,
}: {
  id: Panel;
  label: string;
  note?: string;
  open: boolean;
  onToggle: (panel: Panel) => void;
  children: React.ReactNode;
}) {
  return (
    <div className="proposals-legend-anchor">
      <button
        type="button"
        className={
          open ? 'proposals-legend-button is-open' : 'proposals-legend-button'
        }
        aria-expanded={open}
        onClick={() => onToggle(id)}
      >
        <span>{label}</span>
        {/* Filter state has to show on the closed button: with the legend
            hidden there is nothing else to say the graph is filtered. */}
        {note && <span className="proposals-legend-badge">{note}</span>}
        <Icon
          aria-hidden="true"
          className="proposals-legend-chevron"
          name="expand_more"
        />
      </button>
      {open && (
        <div
          className="proposals-legend-popover"
          role="group"
          aria-label={label}
        >
          {children}
        </div>
      )}
    </div>
  );
}

/**
 * The graph's two legends, as popovers over the canvas: groups (node hue)
 * and relationships (edge color and stroke, which double as the filter).
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
  const [open, setOpen] = useState<Panel | null>(null);
  const allVisible = visibleKinds.size === EDGE_KINDS.length;

  useEffect(() => {
    if (!open) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') setOpen(null);
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [open]);

  // Names the active filter on the closed button, e.g. "Tension only".
  const filterNote = allVisible
    ? undefined
    : visibleKinds.size === 1
      ? `${EDGE_KINDS.find(entry => visibleKinds.has(entry.kind))?.label} only`
      : `${visibleKinds.size} of ${EDGE_KINDS.length}`;

  function toggle(panel: Panel) {
    setOpen(current => (current === panel ? null : panel));
  }

  return (
    <div className="proposals-legend">
      <LegendPopover
        id="groups"
        label="Groups"
        open={open === 'groups'}
        onToggle={toggle}
      >
        <ul className="proposals-legend-list">
          {clusters.map(cluster => (
            <li key={cluster.id} className="proposals-legend-item">
              <span
                className={`proposals-legend-swatch is-${cluster.id}`}
                aria-hidden="true"
              />
              <span>
                <b>{cluster.label}</b> — {cluster.blurb}
              </span>
            </li>
          ))}
        </ul>
      </LegendPopover>

      <LegendPopover
        id="relationships"
        label="Relationships"
        note={filterNote}
        open={open === 'relationships'}
        onToggle={toggle}
      >
        <p className="proposals-legend-hint">
          Select one to show only that kind
        </p>
        <ul className="proposals-legend-list">
          {EDGE_KINDS.map(({kind, label, blurb}) => {
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
                  <span>
                    <b>{label}</b> — {blurb}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
        {!allVisible && (
          <button type="button" className="proposals-reset" onClick={onReset}>
            Show all relationships
          </button>
        )}
      </LegendPopover>
    </div>
  );
}
