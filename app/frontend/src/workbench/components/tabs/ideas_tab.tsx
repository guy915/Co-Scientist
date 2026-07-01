import '@material/web/icon/icon.js';
import type {MouseEvent, ReactNode} from 'react';
import {useMemo, useState} from 'react';
import type {CitationRow, Hypothesis, MatchRow, Review} from '@/api/runs';
import {smoothScrollToSection} from '@/lib/smooth_scroll';

const IDEA_SPLIT_SHELL_CLASSES =
  'idea-split-shell h-full overflow-hidden rounded-none border-0 bg-[var(--cosci-bg)] shadow-none';

const IDEA_SPLIT_GRID_CLASSES =
  'idea-split-grid reference grid h-full min-h-0 min-w-0 ' +
  'grid-cols-[minmax(24rem,0.66fr)_minmax(0,1.25fr)_15rem] ' +
  'max-[720px]:grid-cols-1';

const IDEA_RANK_LIST_CLASSES =
  'idea-rank-list m-0 grid content-start gap-[0.7rem] overflow-y-auto ' +
  'border-r border-[var(--idea-list-border)] bg-transparent py-5 pr-6 ' +
  'pl-5 list-none';

const IDEA_RANK_ROW_CLASSES =
  'idea-rank-row grid min-h-[8.9rem] w-full cursor-pointer ' +
  'grid-cols-[1.75rem_minmax(0,1fr)] items-start gap-[0.65rem] rounded-lg ' +
  'border border-[var(--idea-row-border)] bg-[var(--idea-row-bg)] ' +
  'p-[0.9rem] text-left text-[var(--idea-row-text)] ' +
  'hover:border-[var(--idea-row-hover-border)] ' +
  'hover:bg-[var(--idea-row-hover-bg)]';

const IDEA_RANK_SELECTED_CLASSES =
  'selected !border-[var(--idea-row-selected-border)] ' +
  '!bg-[var(--idea-row-selected-bg)] shadow-none ' +
  'hover:!border-[var(--idea-row-selected-border)] ' +
  'hover:!bg-[var(--idea-row-selected-hover-bg)]';

const IDEA_CHIP_CLASSES =
  'inline-grid h-7 min-w-7 place-items-center rounded-full border-0 ' +
  'bg-[var(--idea-chip-bg)] text-[0.78rem] font-medium ' +
  'text-[var(--idea-chip-text)]';

const IDEA_ELO_CHIP_CLASSES = `${IDEA_CHIP_CLASSES} idea-elo-chip mb-3 w-fit min-w-[6.35rem]`;

const IDEA_RANK_CONTENT_CLASSES = 'idea-rank-content min-w-0';

const IDEA_RANK_TITLE_CLASSES =
  'idea-rank-title mt-[0.15rem] block overflow-hidden text-ellipsis ' +
  'whitespace-nowrap text-[0.9rem] leading-[1.3] font-semibold ' +
  'text-[var(--idea-title-text)]';

const IDEA_RANK_PREVIEW_CLASSES =
  'idea-rank-preview mt-[0.45rem] line-clamp-2 overflow-hidden ' +
  'text-[0.72rem] leading-[1.35] text-[var(--idea-preview-text)]';

const IDEA_DETAIL_PANE_CLASSES =
  'idea-detail-pane grid min-w-0 content-start gap-[1.35rem] overflow-x-hidden ' +
  'overflow-y-auto border-r-0 bg-transparent px-7 pt-[1.45rem] pb-14';

const IDEA_DETAIL_EMPTY_CLASSES =
  `${IDEA_DETAIL_PANE_CLASSES} empty place-items-center text-center ` +
  'text-[var(--md-sys-color-on-surface-variant)]';

const IDEA_BREADCRUMB_CLASSES =
  'idea-breadcrumb inline-flex h-[1.65rem] min-h-[1.65rem] w-fit max-w-full ' +
  'items-center overflow-hidden rounded bg-[var(--idea-breadcrumb-bg)] ' +
  'px-[0.45rem] text-[0.78rem] leading-[1.65rem] font-semibold ' +
  'text-ellipsis whitespace-nowrap text-[var(--idea-breadcrumb-text)]';

const IDEA_BREADCRUMB_TEXT_CLASSES =
  'overflow-hidden text-ellipsis leading-[1.65rem]';

const IDEA_DETAIL_SECTION_CLASSES =
  'idea-detail-section grid gap-[0.45rem] border-t-0 pt-0 ' +
  '[&_h2]:m-0 [&_h2]:text-[clamp(1.5rem,2.2vw,1.9rem)] ' +
  '[&_h2]:leading-[1.15] [&_h2]:font-normal ' +
  '[&_h2]:text-[var(--idea-title-text)] [&_h3]:m-0 ' +
  '[&_h3]:text-base [&_h3]:font-semibold [&_h3]:normal-case ' +
  '[&_h3]:text-[var(--idea-title-text)] [&_p]:m-0 ' +
  '[&_p]:[overflow-wrap:anywhere] [&_p]:text-[0.88rem] ' +
  '[&_p]:leading-[1.5] [&_p]:text-[var(--idea-detail-text)]';

const IDEA_SECTIONS_RAIL_CLASSES =
  'idea-sections-rail mt-5 mr-5 ml-2 grid min-w-0 self-start gap-[1.1rem] ' +
  'rounded-[0.45rem] bg-[var(--cosci-panel)] p-4 max-[720px]:hidden';

const IDEA_SECTIONS_LABEL_CLASSES = 'text-[0.78rem] text-[var(--cosci-muted)]';

const IDEA_SECTION_LINK_CLASSES =
  'text-[0.9rem] leading-[1.35] font-semibold text-[var(--cosci-blue)] ' +
  'no-underline';

/**
 * Renders generated hypotheses in the Google-style split-pane pattern.
 *
 * @param props The hypotheses, citations, reviews, matches, and optional
 *   handler invoked when a user asks for the legacy full-detail modal.
 */
export function IdeasTab({
  hypotheses,
  citations,
  reviews,
  matches = [],
}: {
  hypotheses: Hypothesis[];
  citations: CitationRow[];
  reviews: Review[];
  matches?: MatchRow[];
}) {
  // Kept in the API contract for other tabs/tests; the reference list view does
  // not render citation counters.
  void citations;
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const sorted = useMemo(() => {
    const arr = [...hypotheses];
    arr.sort((a, b) => b.elo_rating - a.elo_rating);
    return arr;
  }, [hypotheses]);

  const selected = useMemo(() => {
    if (!sorted.length) return null;
    return sorted.find(h => h.id === selectedId) ?? sorted[0];
  }, [sorted, selectedId]);

  if (!hypotheses.length) {
    return (
      <Empty msg="Hypotheses appear here once the generation node runs." />
    );
  }

  return (
    <div className={IDEA_SPLIT_SHELL_CLASSES}>
      <div className={IDEA_SPLIT_GRID_CLASSES}>
        <ol
          className={IDEA_RANK_LIST_CLASSES}
          aria-label="Ranked hypothesis list"
        >
          {sorted.map((h, index) => (
            <IdeaListItem
              key={h.id}
              rank={index + 1}
              hypothesis={h}
              selected={h.id === selected?.id}
              onSelect={() => setSelectedId(h.id)}
            />
          ))}
        </ol>
        <HypothesisDetail
          hypothesis={selected}
          reviews={reviews.filter(r => r.hypothesis_id === selected?.id)}
          matches={matches.filter(
            match =>
              match.winner_id === selected?.id ||
              match.loser_id === selected?.id,
          )}
        />
        <SectionsRail />
      </div>
    </div>
  );
}

function IdeaListItem({
  rank,
  hypothesis,
  selected,
  onSelect,
}: {
  rank: number;
  hypothesis: Hypothesis;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <li>
      <button
        type="button"
        className={
          selected
            ? `${IDEA_RANK_ROW_CLASSES} ${IDEA_RANK_SELECTED_CLASSES}`
            : IDEA_RANK_ROW_CLASSES
        }
        onClick={onSelect}
      >
        <span className={`idea-rank-number ${IDEA_CHIP_CLASSES}`}>{rank}</span>
        <span className={IDEA_RANK_CONTENT_CLASSES}>
          <span className={IDEA_ELO_CHIP_CLASSES}>
            Elo rating: {hypothesis.elo_rating}
          </span>
          <span className={IDEA_RANK_TITLE_CLASSES}>{hypothesis.title}</span>
          <span className={IDEA_RANK_PREVIEW_CLASSES}>
            {hypothesis.statement}
          </span>
        </span>
      </button>
    </li>
  );
}

function HypothesisDetail({
  hypothesis,
  reviews,
  matches,
}: {
  hypothesis: Hypothesis | null;
  reviews: Review[];
  matches: MatchRow[];
}) {
  if (!hypothesis) {
    return (
      <section className={IDEA_DETAIL_EMPTY_CLASSES}>
        <md-icon aria-hidden="true">format_list_numbered</md-icon>
        <p>Select a hypothesis to inspect the review and tournament details.</p>
      </section>
    );
  }

  const review = reviews[0] ?? null;
  const latestMatch = [...matches].sort(
    (a, b) => b.created_at - a.created_at,
  )[0];
  const totalMatches = hypothesis.win_count + hypothesis.loss_count;

  return (
    <section
      className={IDEA_DETAIL_PANE_CLASSES}
      aria-label="Hypothesis detail"
    >
      <div className={IDEA_BREADCRUMB_CLASSES}>
        <span className={IDEA_BREADCRUMB_TEXT_CLASSES}>
          AI Co-Scientist &gt; Ranked hypothesis &gt; {hypothesis.title}
        </span>
      </div>

      <DetailSection title="Hypothesis overview" level={2}>
        <p>{hypothesis.statement}</p>
      </DetailSection>

      <DetailSection title="Description" level={2}>
        <h3>{hypothesis.title}</h3>
        {hypothesis.mechanism && (
          <p>
            <strong>Proposed mechanism of action:</strong>{' '}
            {hypothesis.mechanism}
          </p>
        )}
        {hypothesis.expected_effect && (
          <p>
            <strong>Expected effect:</strong> {hypothesis.expected_effect}
          </p>
        )}
      </DetailSection>

      <DetailSection title="Review summary" level={2}>
        <p>
          {review?.summary ||
            'Reviewer notes will appear after the review node completes.'}
        </p>
      </DetailSection>

      <DetailSection title="Full review" level={2}>
        <p>{review?.critique || 'No full review has been recorded yet.'}</p>
      </DetailSection>

      <DetailSection title="Tournament performance" level={2}>
        <p>
          {totalMatches
            ? `${hypothesis.win_count} wins and ${hypothesis.loss_count} losses across ${totalMatches} pairwise matches.`
            : 'No tournament matches have been recorded yet.'}
        </p>
      </DetailSection>

      <DetailSection title="Match summary" level={2}>
        <p>
          {latestMatch?.rationale || 'No match rationale is available yet.'}
        </p>
      </DetailSection>
    </section>
  );
}

function DetailSection({
  title,
  children,
  level = 3,
}: {
  title: string;
  children: ReactNode;
  level?: 2 | 3;
}) {
  const Heading = level === 2 ? 'h2' : 'h3';
  return (
    <section
      className={IDEA_DETAIL_SECTION_CLASSES}
      id={title.toLowerCase().replaceAll(' ', '-')}
    >
      <Heading>{title}</Heading>
      <div>{children}</div>
    </section>
  );
}

function SectionsRail() {
  return (
    <aside className={IDEA_SECTIONS_RAIL_CLASSES} aria-label="Sections">
      <span className={IDEA_SECTIONS_LABEL_CLASSES}>Sections</span>
      {[
        'Hypothesis overview',
        'Description',
        'Review summary',
        'Full review',
        'Tournament performance',
      ].map(item => (
        <a
          key={item}
          href={`#${item.toLowerCase().replaceAll(' ', '-')}`}
          className={IDEA_SECTION_LINK_CLASSES}
          onClick={event =>
            smoothSectionClick(event, item.toLowerCase().replaceAll(' ', '-'))
          }
        >
          {item} &gt;
        </a>
      ))}
    </aside>
  );
}

function smoothSectionClick(
  event: MouseEvent<HTMLAnchorElement>,
  sectionId: string,
) {
  const didScroll = smoothScrollToSection(sectionId, 16);
  if (!didScroll) return;
  event.preventDefault();
}

function Empty({msg}: {msg: string}) {
  return (
    <div
      className="rounded border p-6 text-sm text-center"
      style={{
        borderColor: 'var(--md-sys-color-outline-variant)',
        color: 'var(--md-sys-color-on-surface-variant)',
      }}
    >
      {msg}
    </div>
  );
}
