import {useMemo, useState} from 'react';
import {type Evidence, type KnowledgeBaseTopic, type Report} from '@/api/runs';
import {Icon} from '@/components/icon';
import {splitAbstractSections} from '@/lib/format_abstract';
import {renderInlineHtml} from '@/lib/sanitize_html';
import {capitalizeTerm} from '@/lib/text';
import {
  REPORT_H3_CLASSES,
  REPORT_H4_CLASSES,
  REPORT_SECTION_CLASSES,
  ReportDocument,
} from './run_detail_document';
import {
  ReferencesBlock,
  referenceNumbers,
  resolveCitations,
} from './run_detail_learning_references';

const REPORT_INLINE_ACTION_CLASSES =
  'cosci-inline-action mt-4 inline-flex cursor-pointer items-center ' +
  'gap-[0.3rem] border-0 bg-transparent font-[inherit] text-[0.82rem] ' +
  'text-cosci-fg';

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

function evidenceSection(
  item: Evidence,
  index: number,
  fallbackGoal: string,
): LearningSectionItem {
  return {
    id: `learning-section-${index + 1}`,
    title: learningTitle(item.title, index),
    summary:
      item.abstract ||
      'This section summarizes the concepts, protocols, and ' +
        'methodological constraints Co-Scientist learned while ' +
        `studying ${fallbackGoal}.`,
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
