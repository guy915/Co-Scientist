import {clusters, nodes, type ProposalNode} from './proposals_data';
import {relationsOf} from './proposals_relations';

const ORIGIN_LABEL: Record<ProposalNode['origin'], string> = {
  critique: 'Critique of the paper',
  extension: 'Extension beyond the paper',
};

// One proposal in full. The id anchors it, so a graph selection and a
// deep link into the prose address the same thing.
function ProposalEntry({
  node,
  onSelect,
}: {
  node: ProposalNode;
  onSelect: (id: string) => void;
}) {
  const relations = relationsOf(node.id);
  return (
    <article className="proposals-entry" id={`proposal-${node.id}`}>
      <h3 className="proposals-entry-title">{node.label}</h3>
      <div className="proposals-detail-meta">
        <span className="proposals-tag">{ORIGIN_LABEL[node.origin]}</span>
        {node.source && (
          <span className="proposals-tag is-quiet">Paper {node.source}</span>
        )}
      </div>
      <p>{node.summary}</p>
      <p className="proposals-entry-problem">
        <b>The problem.</b> {node.problem}
      </p>
      <ul className="proposals-relations">
        {relations.map((relation, index) => (
          <li
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
    </article>
  );
}

/**
 * Every proposal written out, grouped by cluster. This is the content the
 * page is indexed and printed from, and what a screen reader reads; it is
 * also what carries the page when the graph does not fit the viewport.
 *
 * @param props.onSelect Open a proposal's detail from a relationship link.
 */
export function ProposalsText({onSelect}: {onSelect: (id: string) => void}) {
  return (
    <div className="proposals-text">
      {clusters.map(cluster => (
        <section key={cluster.id} className="proposals-text-group">
          <h2 className={`proposals-text-group-title is-${cluster.id}`}>
            {cluster.label}
          </h2>
          <p className="proposals-text-group-blurb">{cluster.blurb}</p>
          {nodes
            .filter(node => node.cluster === cluster.id)
            .map(node => (
              <ProposalEntry key={node.id} node={node} onSelect={onSelect} />
            ))}
        </section>
      ))}
    </div>
  );
}
