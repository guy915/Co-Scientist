import {useState} from 'react';
import {type Evidence} from '@/api/runs';
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
  'cosci-inline-action mt-4 inline-flex cursor-pointer items-center gap-[0.3rem] border-0 bg-transparent font-[inherit] text-[0.82rem] text-cosci-fg';

const REPORT_INLINE_ACTION_ICON_CLASSES = 'text-base';

const REFERENCE_SEARCH_CLASSES =
  'cosci-reference-search mb-[1.4rem] flex w-[min(100%,44rem)] items-center gap-3 border-b border-cosci-border px-0 py-[0.45rem] text-cosci-muted';

const REFERENCE_SEARCH_ICON_CLASSES = 'text-base';

const REFERENCE_SEARCH_INPUT_CLASSES =
  'min-w-0 flex-1 border-0 bg-transparent font-[inherit] text-[0.86rem] text-cosci-fg outline-0 placeholder:text-cosci-muted';

const REFERENCE_LIST_CLASSES = 'm-0 grid list-none gap-0 p-0';

const REFERENCE_LIST_ITEM_CLASSES =
  'grid min-h-[3.8rem] grid-cols-[2.2rem_minmax(0,1fr)_auto] items-center gap-[0.8rem] border-b border-cosci-border text-[0.86rem] max-[720px]:grid-cols-[2rem_minmax(0,1fr)]';

const REFERENCE_LIST_INDEX_CLASSES = 'text-cosci-muted';

const REFERENCE_LIST_TITLE_CLASSES = 'font-medium leading-[1.35]';

const REFERENCE_LIST_LINK_CLASSES =
  'reference-open-pill inline-flex items-center gap-[0.35rem] rounded-full border border-cosci-reference-open-border bg-transparent px-[0.7rem] py-[0.3rem] text-[0.78rem] font-medium text-cosci-reference-open-fg no-underline transition-colors hover:border-cosci-reference-open-hover-border hover:bg-cosci-reference-open-hover-bg max-[720px]:col-start-2 max-[720px]:w-fit';

const REFERENCE_LIST_LINK_ICON_CLASSES = 'text-base';

export function LearningView({
  goal,
  evidence,
}: {
  goal: string;
  evidence: Evidence[];
}) {
  const [query, setQuery] = useState('');
  const [expandedSectionIds, setExpandedSectionIds] = useState<string[]>([]);
  const sections = learningSections(goal, evidence);
  const filteredReferences = evidence.filter(item => {
    const haystack = `${item.title} ${item.source} ${item.authors.join(' ')}`;
    return haystack.toLowerCase().includes(query.trim().toLowerCase());
  });
  function toggleSection(sectionId: string) {
    setExpandedSectionIds(current =>
      current.includes(sectionId)
        ? current.filter(id => id !== sectionId)
        : [...current, sectionId],
    );
  }

  return (
    <ReportDocument title="Learning">
      {sections.map(section => {
        const expanded = expandedSectionIds.includes(section.id);
        return (
          <section
            key={section.id}
            id={section.id}
            className={REPORT_SECTION_CLASSES}
          >
            <h3
              className={REPORT_H3_CLASSES}
              dangerouslySetInnerHTML={{
                __html: renderInlineHtml(section.title),
              }}
            />
            <h4 className={REPORT_H4_CLASSES}>Summary</h4>
            <AbstractBody text={section.summary} />
            {expanded && (
              <>
                <h4 className={REPORT_H4_CLASSES}>Details</h4>
                <p
                  dangerouslySetInnerHTML={{
                    __html: renderInlineHtml(section.detail),
                  }}
                />
              </>
            )}
            <button
              type="button"
              className={REPORT_INLINE_ACTION_CLASSES}
              aria-expanded={expanded}
              onClick={() => toggleSection(section.id)}
            >
              <span>{expanded ? 'Show less' : 'Show more'}</span>
              <Icon
                className={REPORT_INLINE_ACTION_ICON_CLASSES}
                aria-hidden="true"
                name={expanded ? 'expand_less' : 'expand_more'}
              />
            </button>
          </section>
        );
      })}
      <ReferencesBlock
        evidence={filteredReferences}
        query={query}
        onQueryChange={setQuery}
      />
    </ReportDocument>
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
      <ol className={REFERENCE_LIST_CLASSES}>
        {evidence.length ? (
          evidence.map((item, index) => (
            <li className={REFERENCE_LIST_ITEM_CLASSES} key={item.id}>
              <span className={REFERENCE_LIST_INDEX_CLASSES}>
                [{index + 1}]
              </span>
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
    </section>
  );
}

function learningSections(goal: string, evidence: Evidence[]) {
  const fallbackGoal =
    goal ||
    'the biological mechanisms and experimental systems relevant to this research goal';
  const seedEvidence = evidence.length
    ? evidence
    : [
        {
          id: 'learning-fallback',
          title: 'Research context and technical definitions',
          abstract:
            'Co-Scientist is assembling the terminology, methods, and biological context needed to evaluate the research goal.',
          source: 'Co-Scientist',
          authors: ['Co-Scientist'],
          year: null,
          url: '',
          available: false,
        },
      ];

  return seedEvidence.slice(0, 3).map((item, index) => ({
    id: `learning-section-${index + 1}`,
    title: learningTitle(item.title, index),
    summary:
      item.abstract ||
      `This section summarizes the concepts, protocols, and methodological constraints Co-Scientist learned while studying ${fallbackGoal}.`,
    detail:
      item.source && item.year
        ? `Source context: ${item.source}, ${item.year}. Co-Scientist keeps this learning available for downstream hypothesis generation, ranking, and synthesis.`
        : `Co-Scientist keeps this learning available for downstream hypothesis generation, ranking, and synthesis for ${fallbackGoal}.`,
  }));
}

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
