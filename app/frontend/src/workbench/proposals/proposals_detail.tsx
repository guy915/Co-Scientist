import {Icon} from '@/components/icon';
import {clusters, type ProposalNode} from './proposals_data';
import {relationsOf} from './proposals_relations';

const ORIGIN_LABEL: Record<ProposalNode['origin'], string> = {
  critique: 'Critique of the paper',
  extension: 'Extension beyond the paper',
};

/**
 * Detail for one proposal: what it is, the weakness it addresses, and every
 * relationship with its rationale. Related names are buttons, so the
 * argument can be walked from node to node.
 *
 * @param props.node The selected proposal.
 * @param props.onSelect Walk to a related proposal.
 * @param props.onClose Dismiss the panel.
 */
export function ProposalsDetail({
  node,
  leaving = false,
  onSelect,
  onClose,
  onLeft,
}: {
  node: ProposalNode;
  /** True once the panel has been dismissed and is sliding back out. */
  leaving?: boolean;
  onSelect: (id: string) => void;
  onClose: () => void;
  onLeft?: () => void;
}) {
  const cluster = clusters.find(entry => entry.id === node.cluster);
  const relations = relationsOf(node.id);
  return (
    <aside
      className={leaving ? 'proposals-detail is-leaving' : 'proposals-detail'}
      aria-label={`${node.label} detail`}
      aria-hidden={leaving || undefined}
      onAnimationEnd={leaving ? onLeft : undefined}
    >
      <header className="proposals-detail-head">
        <div>
          <p className={`proposals-detail-cluster is-${node.cluster}`}>
            {cluster?.label}
          </p>
          <h2 className="proposals-detail-title">{node.label}</h2>
        </div>
        <button
          type="button"
          className="proposals-detail-close"
          aria-label="Close detail"
          onClick={onClose}
        >
          <Icon aria-hidden="true" name="close" />
        </button>
      </header>

      <p className="proposals-detail-summary">{node.summary}</p>

      <div className="proposals-detail-meta">
        <span className="proposals-tag">{ORIGIN_LABEL[node.origin]}</span>
        {node.source && (
          <span className="proposals-tag is-quiet">Paper {node.source}</span>
        )}
      </div>

      <section className="proposals-detail-section">
        <h3 className="proposals-detail-subtitle">The problem</h3>
        <p>{node.problem}</p>
      </section>

      <section className="proposals-detail-section">
        <h3 className="proposals-detail-subtitle">
          Relationships ({relations.length})
        </h3>
        <ul className="proposals-relations">
          {relations.map((relation, index) => (
            <li
              // A pair can carry two edges, so the kind and index are part
              // of the key.
              key={`${relation.other.id}-${relation.kind}-${index}`}
              className={`proposals-relation is-${relation.kind}`}
            >
              <p className="proposals-relation-head">
                {relation.phrase}{' '}
                <button
                  type="button"
                  className="proposals-relation-link"
                  onClick={() => onSelect(relation.other.id)}
                >
                  {relation.other.label}
                </button>
              </p>
              <p className="proposals-relation-note">{relation.note}</p>
            </li>
          ))}
        </ul>
      </section>
    </aside>
  );
}
