import {useMemo, useState} from 'react';
import {type Evidence, type Report} from '@/api/runs';
import {Icon} from '@/components/icon';
import {splitAbstractSections} from '@/lib/format_abstract';
import {renderInlineHtml} from '@/lib/sanitize_html';
import {
  REPORT_H3_CLASSES,
  REPORT_H4_CLASSES,
  REPORT_SECTION_CLASSES,
  ReportDocument,
} from './run_detail_document';

const REPORT_INLINE_ACTION_CLASSES =
  'cosci-inline-action mt-4 inline-flex cursor-pointer items-center ' +
  'gap-[0.3rem] border-0 bg-transparent font-[inherit] text-[0.82rem] ' +
  'text-cosci-fg';

const REPORT_INLINE_ACTION_ICON_CLASSES = 'text-base';

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
  'max-[720px]:grid-cols-[2rem_minmax(0,1fr)]';

const REFERENCE_LIST_INDEX_CLASSES = 'text-cosci-muted';

const REFERENCE_LIST_TITLE_CLASSES = 'font-medium leading-[1.35]';

const REFERENCE_LIST_LINK_CLASSES =
  'reference-open-pill inline-flex items-center gap-[0.35rem] rounded-full ' +
  'border border-cosci-reference-open-border bg-transparent px-[0.7rem] ' +
  'py-[0.3rem] text-[0.78rem] font-medium text-cosci-reference-open-fg ' +
  'no-underline transition-colors ' +
  'hover:border-cosci-reference-open-hover-border ' +
  'hover:bg-cosci-reference-open-hover-bg max-[720px]:col-start-2 ' +
  'max-[720px]:w-fit';

const REFERENCE_LIST_LINK_ICON_CLASSES = 'text-base';

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
        />
      ))}
      <ReferencesBlock
        evidence={filteredReferences}
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
}: {
  detail: string;
  uncertainty?: string;
  referenceIds: string[];
}) {
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
      {referenceIds.length ? (
        <p>
          <strong>Supporting references: </strong>
          {referenceIds.map((id, index) => (
            <span key={id}>
              {index ? ', ' : ''}
              <a href={`#reference-${id}`}>[{index + 1}]</a>
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
}: {
  section: LearningSectionItem;
  expanded: boolean;
  onToggle: () => void;
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

// Search box plus numbered reference list. `evidence` is expected to already
// be filtered by the caller's query; this component only renders it and
// reports query changes back up via onQueryChange (controlled input).
function ReferencesBlock({
  evidence,
  query,
  onQueryChange,
}: {
  evidence: Evidence[];
  query: string;
  onQueryChange: (value: string) => void;
}) {
  return (
    <section className={`${REPORT_SECTION_CLASSES} cosci-reference-list`}>
      <h3 className={REPORT_H3_CLASSES}>References</h3>
      <ReferenceSearchBox query={query} onQueryChange={onQueryChange} />
      <ReferenceList evidence={evidence} />
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
function ReferenceList({evidence}: {evidence: Evidence[]}) {
  return (
    <ol className={REFERENCE_LIST_CLASSES}>
      {evidence.length ? (
        evidence.map((item, index) => (
          <ReferenceListItem key={item.id} item={item} index={index} />
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

// One numbered reference row: title plus an optional "Open" link.
function ReferenceListItem({item, index}: {item: Evidence; index: number}) {
  return (
    <li id={`reference-${item.id}`} className={REFERENCE_LIST_ITEM_CLASSES}>
      <span className={REFERENCE_LIST_INDEX_CLASSES}>[{index + 1}]</span>
      <strong
        className={REFERENCE_LIST_TITLE_CLASSES}
        dangerouslySetInnerHTML={{__html: renderInlineHtml(item.title)}}
      />
      {item.url ? (
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
      ) : null}
    </li>
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

// Builds up to three display sections (title/summary/detail) from the run's
// evidence. When no evidence has been gathered yet (early in a run), a single
// placeholder item is used instead so the tab still shows meaningful copy
// rather than an empty page.
function learningSections(
  goal: string,
  evidence: Evidence[],
  report: Report | null,
): LearningSectionItem[] {
  const persistedTopics = report?.payload.knowledge_base || [];
  if (persistedTopics.length) {
    return persistedTopics.map(topic => ({
      id: topic.id,
      title: topic.title,
      summary: topic.summary,
      detail: topic.detail,
      uncertainty: topic.uncertainty,
      referenceIds: topic.reference_ids,
    }));
  }
  const fallbackGoal =
    goal ||
    'the biological mechanisms and experimental systems relevant to this research goal';
  if (!evidence.length) {
    return [
      {
        id: 'knowledge-unavailable',
        title: 'Knowledge synthesis unavailable',
        summary:
          'No evidence-backed technical topics have been synthesized for this run.',
        detail: `The run must retrieve and verify evidence before it can build a Knowledge Base for ${fallbackGoal}.`,
        referenceIds: [],
      },
    ];
  }

  return evidence.slice(0, 3).map((item, index) => ({
    id: `learning-section-${index + 1}`,
    title: learningTitle(item.title, index),
    summary:
      item.abstract ||
      `This section summarizes the concepts, protocols, and methodological constraints Co-Scientist learned while studying ${fallbackGoal}.`,
    // Detail expands on the summary with source attribution when available,
    // otherwise a generic note tying the item back to the research goal.
    detail:
      item.source && item.year
        ? `Source context: ${item.source}, ${item.year}. Co-Scientist keeps this learning available for downstream hypothesis generation, ranking, and synthesis.`
        : `Co-Scientist keeps this learning available for downstream hypothesis generation, ranking, and synthesis for ${fallbackGoal}.`,
    referenceIds: [item.id],
  }));
}

// Strips a leading "H1: " style hypothesis-id prefix and title-cases the
// remaining words (lowercasing small connector words), falling back to a
// numbered placeholder when nothing is left after stripping.
function learningTitle(title: string, index: number): string {
  const cleaned = title.replace(/^H\d+:\s*/i, '').trim();
  if (!cleaned) return `Learning Section ${index + 1}`;
  return cleaned
    .split(/\s+/)
    .map(word =>
      /^(and|or|the|of|in|for|to|with|by)$/i.test(word)
        ? word.toLowerCase()
        : word.charAt(0).toUpperCase() + word.slice(1),
    )
    .join(' ');
}
