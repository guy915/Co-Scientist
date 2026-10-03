import {useMemo, useState} from 'react';
import type {Evidence, KnowledgeBaseTopic, Report} from '@/api/runs';
import {Icon} from '@/components/icon';
import {splitAbstractSections, capitalizeTerm} from '@/lib/text';
import {renderInlineHtml} from '@/lib/sanitize_html';
import {
  REPORT_H3_CLASSES,
  REPORT_H4_CLASSES,
  REPORT_SECTION_CLASSES,
  ReportDocument,
} from './run_detail_shell';

const REPORT_INLINE_ACTION_CLASSES =
  'cosci-inline-action mt-4 inline-flex cursor-pointer items-center ' +
  'gap-[0.3rem] border-0 bg-transparent font-[inherit] text-[0.82rem] ' +
  'text-cosci-fg pointer-coarse:min-h-11';

const REPORT_INLINE_ACTION_ICON_CLASSES = 'text-base';

// State and derived data behind the "Learning" tab: the synthesized sections
// (see learningSections), the query-filtered reference list, and the
// per-section "Details" expand/collapse toggle.
function useLearningViewState(
  goal: string,
  evidence: Evidence[],
  report: Report | null,
) {
  const [query, setQuery] = useState('');
  // Section ids currently showing their "Details" block; toggled independently
  // per section so expanding one does not affect the others.
  const [expandedSectionIds, setExpandedSectionIds] = useState<string[]>([]);
  const sections = useMemo(
    () => learningSections(goal, evidence, report),
    [goal, evidence, report],
  );
  // Built from the unfiltered evidence so searching the reference list never
  // renumbers a citation out from under the reader.
  const referenceNumberById = useMemo(
    () => referenceNumbers(evidence),
    [evidence],
  );
  // Case-insensitive substring match across title, source, and authors.
  const filteredReferences = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return evidence.filter(item => {
      const haystack = `${item.title} ${item.source} ${item.authors.join(' ')}`;
      return haystack.toLowerCase().includes(needle);
    });
  }, [evidence, query]);
  function toggleSection(sectionId: string) {
    setExpandedSectionIds(current =>
      current.includes(sectionId)
        ? current.filter(id => id !== sectionId)
        : [...current, sectionId],
    );
  }

  return {
    sections,
    filteredReferences,
    referenceNumberById,
    query,
    setQuery,
    expandedSectionIds,
    toggleSection,
  };
}

/**
 * Renders the "Learning" tab: up to three synthesized summary sections
 * (derived from the run's evidence, or a fallback placeholder when none has
 * been gathered yet) followed by a searchable reference list.
 *
 * @param props The research goal (used in fallback copy) and the run's
 *   collected evidence.
 */
export function LearningView({
  goal,
  evidence,
  report = null,
}: {
  goal: string;
  evidence: Evidence[];
  report?: Report | null;
}) {
  const {
    sections,
    filteredReferences,
    referenceNumberById,
    query,
    setQuery,
    expandedSectionIds,
    toggleSection,
  } = useLearningViewState(goal, evidence, report);

  return (
    <ReportDocument title="Knowledge Base">
      {sections.map(section => (
        <LearningSectionBlock
          key={section.id}
          section={section}
          expanded={expandedSectionIds.includes(section.id)}
          onToggle={() => toggleSection(section.id)}
          referenceNumberById={referenceNumberById}
        />
      ))}
      <ReferencesBlock
        evidence={filteredReferences}
        referenceNumberById={referenceNumberById}
        query={query}
        onQueryChange={setQuery}
      />
    </ReportDocument>
  );
}

// Expanded "Details" block within a Learning section: renders nothing when
// collapsed, so the caller can render it unconditionally.
function LearningSectionDetailsBlock({
  detail,
  uncertainty,
  referenceIds,
  referenceNumberById,
}: {
  detail: string;
  uncertainty?: string;
  referenceIds: string[];
  referenceNumberById: Map<string, number>;
}) {
  const citations = resolveCitations(referenceIds, referenceNumberById);
  return (
    <>
      <h4 className={REPORT_H4_CLASSES}>Details</h4>
      <p
        dangerouslySetInnerHTML={{
          __html: renderInlineHtml(detail),
        }}
      />
      {uncertainty ? (
        <p>
          <strong>Uncertainty: </strong>
          {uncertainty}
        </p>
      ) : null}
      {citations.length ? (
        <p>
          <strong>Supporting references: </strong>
          {citations.map((citation, index) => (
            <span key={citation.id}>
              {index ? ', ' : ''}
              <a href={`#reference-${citation.id}`}>[{citation.number}]</a>
            </span>
          ))}
        </p>
      ) : null}
    </>
  );
}

// "Show more"/"Show less" toggle button beneath a Learning section's body.
function LearningSectionToggle({
  expanded,
  onToggle,
}: {
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      className={REPORT_INLINE_ACTION_CLASSES}
      aria-expanded={expanded}
      onClick={onToggle}
    >
      <span>{expanded ? 'Show less' : 'Show more'}</span>
      <Icon
        className={REPORT_INLINE_ACTION_ICON_CLASSES}
        aria-hidden="true"
        name={expanded ? 'expand_less' : 'expand_more'}
      />
    </button>
  );
}

// One "Learning" tab summary section: title, summary body, an optional
// expanded "Details" block, and the toggle button that drives `expanded`.
function LearningSectionBlock({
  section,
  expanded,
  onToggle,
  referenceNumberById,
}: {
  section: LearningSectionItem;
  expanded: boolean;
  onToggle: () => void;
  referenceNumberById: Map<string, number>;
}) {
  return (
    <section id={section.id} className={REPORT_SECTION_CLASSES}>
      {/* renderInlineHtml sanitizes before this is trusted as HTML, so
          titles/details carrying inline emphasis markup render safely. */}
      <h3
        className={REPORT_H3_CLASSES}
        dangerouslySetInnerHTML={{
          __html: renderInlineHtml(section.title),
        }}
      />
      <h4 className={REPORT_H4_CLASSES}>Summary</h4>
      <AbstractBody text={section.summary} />
      {expanded && (
        <LearningSectionDetailsBlock
          detail={section.detail}
          uncertainty={section.uncertainty}
          referenceIds={section.referenceIds}
          referenceNumberById={referenceNumberById}
        />
      )}
      <LearningSectionToggle expanded={expanded} onToggle={onToggle} />
    </section>
  );
}

// Splits an abstract's text into its labeled sections (e.g. "Background",
// "Methods") via splitAbstractSections and renders each as its own paragraph,
// hiding a redundant "Summary" label since that heading is already shown by
// the caller.
function AbstractBody({text}: {text: string}) {
  const parts = splitAbstractSections(text);
  return (
    <>
      {parts.map((part, index) => {
        const showLabel = part.label && part.label.toLowerCase() !== 'summary';
        return (
          <p key={index}>
            {showLabel ? <strong>{part.label} </strong> : null}
            <span dangerouslySetInnerHTML={{__html: part.html}} />
          </p>
        );
      })}
    </>
  );
}

// One synthesized Learning-tab section, as built by learningSections and
// rendered by LearningSectionBlock.
interface LearningSectionItem {
  id: string;
  title: string;
  summary: string;
  detail: string;
  uncertainty?: string;
  referenceIds: string[];
}

function topicToSection(topic: KnowledgeBaseTopic): LearningSectionItem {
  return {
    id: topic.id,
    title: topic.title,
    summary: topic.summary,
    detail: topic.detail,
    uncertainty: topic.uncertainty,
    referenceIds: topic.reference_ids,
  };
}

// The persisted Knowledge Base, if the report has synthesized one, else null
// so the caller falls back to the live evidence list.
function knowledgeBaseTopics(
  report: Report | null,
): LearningSectionItem[] | null {
  const topics = report?.payload.knowledge_base;
  return topics && topics.length ? topics.map(topicToSection) : null;
}

// The research goal to reference in generated copy, defaulted when the run
// has not recorded one yet.
function resolveFallbackGoal(goal: string): string {
  return (
    goal ||
    'the biological mechanisms and experimental systems relevant to this ' +
      'research goal'
  );
}

// Builds up to three display sections (title/summary/detail) from the run's
// evidence. When no evidence has been gathered yet (early in a run), a single
// placeholder item is used instead so the tab still shows meaningful copy
// rather than an empty page.
function learningSections(
  goal: string,
  evidence: Evidence[],
  report: Report | null,
): LearningSectionItem[] {
  const persistedTopics = knowledgeBaseTopics(report);
  if (persistedTopics) return persistedTopics;
  const fallbackGoal = resolveFallbackGoal(goal);
  if (!evidence.length) return [placeholderSection(fallbackGoal)];
  return evidence
    .slice(0, 3)
    .map((item, index) => evidenceSection(item, index, fallbackGoal));
}

// The single placeholder item shown before any evidence has been gathered,
// so the tab still shows meaningful copy rather than an empty page.
function placeholderSection(fallbackGoal: string): LearningSectionItem {
  return {
    id: 'knowledge-unavailable',
    title: 'Knowledge synthesis unavailable',
    summary:
      'No evidence-backed technical topics have been synthesized for this run.',
    detail:
      'The run must retrieve and verify evidence before it can ' +
      `build a Knowledge Base for ${fallbackGoal}.`,
    referenceIds: [],
  };
}

// Summary copy for a source whose full text was never reachable: it used to
// fall through to the generic learning blurb, presenting an unreachable
// source as if it had been read (D18).
const UNAVAILABLE_SOURCE_SUMMARY =
  'The full source could not be reached when this evidence was gathered, ' +
  'so it is listed without a summary.';

// Summary copy for a retracted source: distinct from the merely-unreachable
// case above, since collapsing the two here reintroduces on the Knowledge
// Base tab the exact conflation the References pill was fixed to avoid.
const RETRACTED_SOURCE_SUMMARY =
  'This source has been retracted, so it is listed without a summary.';

function evidenceSummary(item: Evidence, fallbackGoal: string): string {
  if (item.retracted) return RETRACTED_SOURCE_SUMMARY;
  if (item.available === false) return UNAVAILABLE_SOURCE_SUMMARY;
  return (
    item.abstract ||
    'This section summarizes the concepts, protocols, and ' +
      'methodological constraints Co-Scientist learned while ' +
      `studying ${fallbackGoal}.`
  );
}

function evidenceSection(
  item: Evidence,
  index: number,
  fallbackGoal: string,
): LearningSectionItem {
  return {
    id: `learning-section-${index + 1}`,
    title: learningTitle(item.title, index),
    summary: evidenceSummary(item, fallbackGoal),
    // Detail expands on the summary with source attribution when available,
    // otherwise a generic note tying the item back to the research goal.
    detail:
      item.source && item.year
        ? `Source context: ${item.source}, ${item.year}. Co-Scientist ` +
          'keeps this learning available for downstream hypothesis ' +
          'generation, ranking, and synthesis.'
        : 'Co-Scientist keeps this learning available for downstream ' +
          'hypothesis generation, ranking, and synthesis for ' +
          `${fallbackGoal}.`,
    referenceIds: [item.id],
  };
}

function learningTitle(title: string, index: number): string {
  const cleaned = title.replace(/^H\d+:\s*/i, '').trim();
  if (!cleaned) return `Learning Section ${index + 1}`;
  return cleaned
    .split(/\s+/)
    .map(word =>
      /^(and|or|the|of|in|for|to|with|by)$/i.test(word)
        ? word.toLowerCase()
        : capitalizeTerm(word),
    )
    .join(' ');
}

/**
 * The "References" section of the Knowledge Base tab, plus the numbering that
 * ties it to the citations printed on the topic cards above it.
 *
 * Reference numbers are derived once from the run's full evidence list and
 * shared by both surfaces, so a card's "[73]" and the list's "[73]" always
 * name the same paper -- including while the list is filtered by a search.
 */

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

// A retracted source is a stronger and different claim than "unreachable" --
// the paper was read and the publisher withdrew it -- so it gets its own
// pill rather than folding into the quiet "Unavailable" state above, which a
// reader would otherwise misread as a network or access problem.
const REFERENCE_RETRACTED_CLASSES =
  'reference-retracted-pill inline-flex items-center gap-[0.35rem] ' +
  'rounded-full border border-cosci-danger-border bg-cosci-danger-bg ' +
  'px-[0.7rem] py-[0.3rem] text-[0.78rem] font-medium ' +
  'text-cosci-danger-fg max-[700px]:col-start-2 max-[700px]:w-fit';

const REFERENCE_RETRACTED_TEXT = 'Retracted';

const REFERENCE_RETRACTED_TITLE = 'This source has been retracted';

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
// fetched, a "Retracted" pill when the source itself has been withdrawn, else
// a quiet "Unavailable" pill so a source that was never reachable is plainly
// labelled instead of reading as a normal reference (D18). `retracted` is
// checked first because a retracted source also persists `available: false`
// (the same gates keep treating it as unavailable), so without this order it
// would read as a plain reachability problem rather than a retraction.
function ReferenceSourceState({item}: {item: Evidence}) {
  if (item.retracted) {
    return (
      <span
        className={REFERENCE_RETRACTED_CLASSES}
        title={REFERENCE_RETRACTED_TITLE}
        aria-label={REFERENCE_RETRACTED_TITLE}
      >
        {REFERENCE_RETRACTED_TEXT}
      </span>
    );
  }
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
