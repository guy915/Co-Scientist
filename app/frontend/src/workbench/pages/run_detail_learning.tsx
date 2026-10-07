import {useMemo, useState} from 'react';
import type {Evidence, KnowledgeBaseTopic, Report} from '@/api/runs';
import {Icon} from '@/components/icon';
import {
  Button,
  Chip,
  chipClasses,
  chipIconClasses,
  joinClasses,
} from '@/shared/ui';
import {splitAbstractSections, capitalizeTerm} from '@/lib/text';
import {renderInlineHtml} from '@/lib/sanitize_html';
import {
  REPORT_H3_CLASSES,
  REPORT_H4_CLASSES,
  REPORT_SECTION_CLASSES,
  ReportDocument,
} from './run_detail_shell';

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
    <Button
      variant="text"
      size="sm"
      trailingIcon={expanded ? 'expand_less' : 'expand_more'}
      layoutClassName="mt-4 -ml-2 pointer-coarse:min-h-11"
      aria-expanded={expanded}
      onClick={onToggle}
    >
      <span>{expanded ? 'Show less' : 'Show more'}</span>
    </Button>
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

const REFERENCE_LIST_ITEM_CLASSES =
  'grid min-h-[3.8rem] grid-cols-[2.2rem_minmax(0,1fr)_auto] items-center ' +
  'gap-[0.8rem] border-b border-cosci-border py-[0.7rem] text-[0.86rem] ' +
  'max-[700px]:grid-cols-[2rem_minmax(0,1fr)] max-[700px]:gap-y-[0.55rem] ' +
  'max-[700px]:py-[0.9rem]';

const REFERENCE_UNAVAILABLE_TEXT = 'Unavailable';

const REFERENCE_UNAVAILABLE_TITLE =
  'The full source could not be reached when this evidence was gathered';

const REFERENCE_RETRACTED_TEXT = 'Retracted';

const REFERENCE_RETRACTED_TITLE = 'This source has been retracted';

export interface ReferenceCitation {
  id: string;
  number: number;
}

// Share reference numbering between topic cards and the full list, including
// while search filters that list.
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
    <label className="cosci-reference-search mb-[1.4rem] flex w-[min(100%,44rem)] items-center gap-3 border-b border-cosci-border px-0 py-[0.45rem] text-cosci-muted">
      <Icon className="text-base" aria-hidden="true" name="search" />
      <input
        className="min-w-0 flex-1 border-0 bg-transparent font-[inherit] text-[0.86rem] text-cosci-fg outline-0 placeholder:text-cosci-muted"
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
    <ol className="m-0 grid list-none gap-0 p-0">
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
          <span className="text-cosci-muted">[0]</span>
          <strong className="font-medium leading-[1.35]">
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
      <span className="text-cosci-muted">[{number}]</span>
      <strong
        className="font-medium leading-[1.35]"
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
      <Chip
        variant="outlined"
        tone="danger"
        tooltip={REFERENCE_RETRACTED_TITLE}
        aria-label={REFERENCE_RETRACTED_TITLE}
        layoutClassName="reference-retracted-pill max-[700px]:col-start-2"
      >
        {REFERENCE_RETRACTED_TEXT}
      </Chip>
    );
  }
  if (item.available === false) {
    return (
      <Chip
        variant="outlined"
        tooltip={REFERENCE_UNAVAILABLE_TITLE}
        aria-label={REFERENCE_UNAVAILABLE_TITLE}
        layoutClassName="reference-unavailable-pill max-[700px]:col-start-2"
      >
        {REFERENCE_UNAVAILABLE_TEXT}
      </Chip>
    );
  }
  if (!item.url) return null;
  return (
    <a
      className={joinClasses(
        chipClasses({variant: 'outlined', interactive: true}),
        'reference-open-pill max-[700px]:col-start-2',
      )}
      href={item.url}
      target="_blank"
      rel="noopener noreferrer"
    >
      <Icon
        className={chipIconClasses()}
        aria-hidden="true"
        name="open_in_new"
      />
      Open
    </a>
  );
}
