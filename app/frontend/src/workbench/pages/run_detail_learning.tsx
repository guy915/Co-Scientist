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

function useLearningViewState(
  goal: string,
  evidence: Evidence[],
  report: Report | null,
) {
  const [query, setQuery] = useState('');
  const [expandedSectionIds, setExpandedSectionIds] = useState<string[]>([]);
  const sections = useMemo(
    () => learningSections(goal, evidence, report),
    [goal, evidence, report],
  );
  // Build numbering from unfiltered evidence so searching never renumbers
  // citations.
  const referenceNumberById = useMemo(
    () => referenceNumbers(evidence),
    [evidence],
  );
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

function knowledgeBaseTopics(
  report: Report | null,
): LearningSectionItem[] | null {
  const topics = report?.payload.knowledge_base;
  return topics && topics.length ? topics.map(topicToSection) : null;
}

function resolveFallbackGoal(goal: string): string {
  return (
    goal ||
    'the biological mechanisms and experimental systems relevant to this ' +
      'research goal'
  );
}

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

// Unreachable source copy must not imply its full text was read.
const UNAVAILABLE_SOURCE_SUMMARY =
  'The full source could not be reached when this evidence was gathered, ' +
  'so it is listed without a summary.';

// Retraction differs from unreachable; do not present withdrawal as a network
// failure.
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

// Share reference numbering between topic cards and the full list, including
// while search filters that list.

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

const REFERENCE_UNAVAILABLE_CLASSES =
  'reference-unavailable-pill inline-flex items-center gap-[0.35rem] ' +
  'rounded-full border border-cosci-border bg-transparent px-[0.7rem] ' +
  'py-[0.3rem] text-[0.78rem] font-medium text-cosci-muted ' +
  'max-[700px]:col-start-2 max-[700px]:w-fit';

const REFERENCE_UNAVAILABLE_TEXT = 'Unavailable';

const REFERENCE_UNAVAILABLE_TITLE =
  'The full source could not be reached when this evidence was gathered';

const REFERENCE_RETRACTED_CLASSES =
  'reference-retracted-pill inline-flex items-center gap-[0.35rem] ' +
  'rounded-full border border-cosci-danger-border bg-cosci-danger-bg ' +
  'px-[0.7rem] py-[0.3rem] text-[0.78rem] font-medium ' +
  'text-cosci-danger-fg max-[700px]:col-start-2 max-[700px]:w-fit';

const REFERENCE_RETRACTED_TEXT = 'Retracted';

const REFERENCE_RETRACTED_TITLE = 'This source has been retracted';

export interface ReferenceCitation {
  id: string;
  number: number;
}

export function referenceNumbers(evidence: Evidence[]): Map<string, number> {
  return new Map(evidence.map((item, index) => [item.id, index + 1]));
}

// Omit unresolved citation ids: they have neither a valid number nor a
// destination.
export function resolveCitations(
  referenceIds: string[],
  numberById: Map<string, number>,
): ReferenceCitation[] {
  return referenceIds
    .map(id => ({id, number: numberById.get(id) ?? 0}))
    .filter(citation => citation.number > 0)
    .sort((first, second) => first.number - second.number);
}

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

// Check retraction before availability: retracted rows also persist
// available=false.
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
