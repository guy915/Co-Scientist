/**
 * The "References" section of the Knowledge Base tab, plus the numbering that
 * ties it to the citations printed on the topic cards above it.
 *
 * Reference numbers are derived once from the run's full evidence list and
 * shared by both surfaces, so a card's "[73]" and the list's "[73]" always
 * name the same paper -- including while the list is filtered by a search.
 */
import {type Evidence} from '@/api/runs';
import {Icon} from '@/components/icon';
import {renderInlineHtml} from '@/lib/sanitize_html';
import {REPORT_H3_CLASSES, REPORT_SECTION_CLASSES} from './run_detail_document';

const REFERENCE_SEARCH_CLASSES =
  'cosci-reference-search mb-[1.4rem] flex w-[min(100%,44rem)] items-center ' +
  'gap-3 border-b border-cosci-border px-0 py-[0.45rem] text-cosci-muted';

const REFERENCE_SEARCH_ICON_CLASSES = 'text-base';

const REFERENCE_SEARCH_INPUT_CLASSES =
  'min-w-0 flex-1 border-0 bg-transparent font-[inherit] text-[0.86rem] ' +
  'text-cosci-fg outline-0 placeholder:text-cosci-muted';

const REFERENCE_LIST_CLASSES = 'm-0 grid list-none gap-0 p-0';

const REFERENCE_LIST_ITEM_CLASSES =
  'grid min-h-[3.8rem] grid-cols-[2.2rem_minmax(0,1fr)_auto] items-center ' +
  'gap-[0.8rem] border-b border-cosci-border text-[0.86rem] ' +
  'max-[700px]:grid-cols-[2rem_minmax(0,1fr)]';

const REFERENCE_LIST_INDEX_CLASSES = 'text-cosci-muted';

const REFERENCE_LIST_TITLE_CLASSES = 'font-medium leading-[1.35]';

const REFERENCE_LIST_LINK_CLASSES =
  'reference-open-pill inline-flex items-center gap-[0.35rem] rounded-full ' +
  'border border-cosci-reference-open-border bg-transparent px-[0.7rem] ' +
  'py-[0.3rem] text-[0.78rem] font-medium text-cosci-reference-open-fg ' +
  'no-underline transition-colors ' +
  'hover:border-cosci-reference-open-hover-border ' +
  'hover:bg-cosci-reference-open-hover-bg max-[700px]:col-start-2 ' +
  'max-[700px]:w-fit';

const REFERENCE_LIST_LINK_ICON_CLASSES = 'text-base';

// The quiet counterpart of the "Open" pill for a source whose full text was
// never reachable: same slot and shape, muted so it reads as a state, not an
// action. An unreachable source used to render identically to a fetched one,
// which presented a degraded knowledge base as normal (D18).
const REFERENCE_UNAVAILABLE_CLASSES =
  'reference-unavailable-pill inline-flex items-center gap-[0.35rem] ' +
  'rounded-full border border-cosci-border bg-transparent px-[0.7rem] ' +
  'py-[0.3rem] text-[0.78rem] font-medium text-cosci-muted ' +
  'max-[700px]:col-start-2 max-[700px]:w-fit';

const REFERENCE_UNAVAILABLE_TEXT = 'Unavailable';

const REFERENCE_UNAVAILABLE_TITLE =
  'The full source could not be reached when this evidence was gathered';

/** One resolved citation: the reference it names and the number to print. */
export interface ReferenceCitation {
  id: string;
  number: number;
}

/**
 * Maps each reference's durable id to its 1-based place in the run's full
 * reference list -- the number the References section prints beside it.
 *
 * @param evidence The run's complete, unfiltered evidence list.
 * @returns Reference number by evidence id.
 */
export function referenceNumbers(evidence: Evidence[]): Map<string, number> {
  return new Map(evidence.map((item, index) => [item.id, index + 1]));
}

/**
 * Resolves a topic's cited evidence ids to reference numbers, ascending.
 *
 * Ids with no matching reference are dropped: they have neither a number to
 * print nor a row to link to, and a citation pointing nowhere reads as a
 * citation to the wrong paper.
 *
 * @param referenceIds The evidence ids a Knowledge Base topic cites.
 * @param numberById Reference numbers, as built by referenceNumbers.
 * @returns The printable citations, ordered by reference number.
 */
export function resolveCitations(
  referenceIds: string[],
  numberById: Map<string, number>,
): ReferenceCitation[] {
  return referenceIds
    .map(id => ({id, number: numberById.get(id) ?? 0}))
    .filter(citation => citation.number > 0)
    .sort((first, second) => first.number - second.number);
}

/**
 * Search box plus numbered reference list.
 *
 * @param props `evidence` is expected to already be filtered by the caller's
 *   query; this component only renders it and reports query changes back up
 *   via onQueryChange (controlled input). `referenceNumberById` must be built
 *   from the unfiltered list so numbers survive filtering.
 */
export function ReferencesBlock({
  evidence,
  referenceNumberById,
  query,
  onQueryChange,
}: {
  evidence: Evidence[];
  referenceNumberById: Map<string, number>;
  query: string;
  onQueryChange: (value: string) => void;
}) {
  return (
    <section className={`${REPORT_SECTION_CLASSES} cosci-reference-list`}>
      <h3 className={REPORT_H3_CLASSES}>References</h3>
      <ReferenceSearchBox query={query} onQueryChange={onQueryChange} />
      <ReferenceList
        evidence={evidence}
        referenceNumberById={referenceNumberById}
      />
    </section>
  );
}

// Controlled search input above the reference list.
function ReferenceSearchBox({
  query,
  onQueryChange,
}: {
  query: string;
  onQueryChange: (value: string) => void;
}) {
  return (
    <label className={REFERENCE_SEARCH_CLASSES}>
      <Icon
        className={REFERENCE_SEARCH_ICON_CLASSES}
        aria-hidden="true"
        name="search"
      />
      <input
        className={REFERENCE_SEARCH_INPUT_CLASSES}
        value={query}
        onChange={event => onQueryChange(event.currentTarget.value)}
        placeholder="Search references"
        aria-label="Search references"
      />
    </label>
  );
}

// Numbered reference list, or a single placeholder row when nothing matches
// the current search.
function ReferenceList({
  evidence,
  referenceNumberById,
}: {
  evidence: Evidence[];
  referenceNumberById: Map<string, number>;
}) {
  return (
    <ol className={REFERENCE_LIST_CLASSES}>
      {evidence.length ? (
        evidence.map(item => (
          <ReferenceListItem
            key={item.id}
            item={item}
            number={referenceNumberById.get(item.id) ?? 0}
          />
        ))
      ) : (
        <li className={REFERENCE_LIST_ITEM_CLASSES}>
          <span className={REFERENCE_LIST_INDEX_CLASSES}>[0]</span>
          <strong className={REFERENCE_LIST_TITLE_CLASSES}>
            No references match the current search.
          </strong>
        </li>
      )}
    </ol>
  );
}

// One numbered reference row: title plus an optional "Open" link. `number` is
// the row's place in the full reference list, not in the filtered view, so it
// matches the citations printed on the topic cards above.
function ReferenceListItem({item, number}: {item: Evidence; number: number}) {
  return (
    <li id={`reference-${item.id}`} className={REFERENCE_LIST_ITEM_CLASSES}>
      <span className={REFERENCE_LIST_INDEX_CLASSES}>[{number}]</span>
      <strong
        className={REFERENCE_LIST_TITLE_CLASSES}
        dangerouslySetInnerHTML={{__html: renderInlineHtml(item.title)}}
      />
      <ReferenceSourceState item={item} />
    </li>
  );
}

// The row's reachability state: an "Open" action when the full source was
// fetched, else a quiet "Unavailable" pill so a source that was never
// reachable is plainly labelled instead of reading as a normal reference
// (D18). `available` is what the store recorded when evidence was gathered.
function ReferenceSourceState({item}: {item: Evidence}) {
  if (item.available === false) {
    return (
      <span
        className={REFERENCE_UNAVAILABLE_CLASSES}
        title={REFERENCE_UNAVAILABLE_TITLE}
        aria-label={REFERENCE_UNAVAILABLE_TITLE}
      >
        {REFERENCE_UNAVAILABLE_TEXT}
      </span>
    );
  }
  if (!item.url) return null;
  return (
    <a
      className={REFERENCE_LIST_LINK_CLASSES}
      href={item.url}
      target="_blank"
      rel="noopener noreferrer"
    >
      <Icon
        className={REFERENCE_LIST_LINK_ICON_CLASSES}
        aria-hidden="true"
        name="open_in_new"
      />
      Open
    </a>
  );
}
