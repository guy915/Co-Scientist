import {useMemo} from 'react';
import {Icon} from '@/components/icon';
import {clusters, type ProposalNode} from './proposals_data';
import {relationsOf, type Relation} from './proposals_relations';

const ORIGIN_LABEL: Record<ProposalNode['origin'], string> = {
  critique: 'Critique of the paper',
  extension: 'Extension beyond the paper',
};

function DetailHeader({
  node,
  onClose,
}: {
  node: ProposalNode;
  onClose: () => void;
}) {
  const cluster = clusters.find(entry => entry.id === node.cluster);
  return (
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
  );
}

// Every relationship with its rationale; related names are buttons, so the
// argument can be walked from node to node.
function RelationsList({
  relations,
  onSelect,
}: {
  relations: Relation[];
  onSelect: (id: string) => void;
}) {
  return (
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
  );
}

/**
 * Detail for one proposal: what it is, the weakness it addresses, and every
 * relationship with its rationale. Related names are buttons, so the
 * argument can be walked from node to node.
 *
 * @param props.node The selected proposal.
 * @param props.onSelect Walk to a related proposal.
 * @param props.onClose Dismiss the panel.
 */
// The proposal's own reading: summary, origin/source tags, and the
// weakness it addresses.
function DetailBody({node}: {node: ProposalNode}) {
  return (
    <>
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
    </>
  );
}

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
  // Static per node, and the page re-renders this panel on every hover
  // elsewhere on the graph, so the derivation may not run per render.
  const relations = useMemo(() => relationsOf(node.id), [node.id]);
  return (
    <aside
      className={leaving ? 'proposals-detail is-leaving' : 'proposals-detail'}
      aria-label={`${node.label} detail`}
      aria-hidden={leaving || undefined}
      onAnimationEnd={leaving ? onLeft : undefined}
    >
      <DetailHeader node={node} onClose={onClose} />
      <DetailBody node={node} />
      <section className="proposals-detail-section">
        <h3 className="proposals-detail-subtitle">
          Relationships ({relations.length})
        </h3>
        <RelationsList relations={relations} onSelect={onSelect} />
      </section>
    </aside>
  );
}
