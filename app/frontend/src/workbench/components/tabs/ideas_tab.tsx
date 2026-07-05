import type {MouseEvent, ReactNode} from 'react';
import {useMemo, useState} from 'react';
import type {Hypothesis, MatchRow, Review} from '@/api/runs';
import {Icon} from '@/components/icon';
import {smoothScrollToSection} from '@/lib/smooth_scroll';
import {EmptyState} from '../empty_state';

const IDEA_SPLIT_SHELL_CLASSES =
  'idea-split-shell flex h-full min-h-0 flex-col overflow-hidden ' +
  'rounded-none border-0 bg-cosci-bg';

const IDEA_SPLIT_GRID_CLASSES =
  'idea-split-grid reference grid min-h-0 min-w-0 flex-1 ' +
  'grid-cols-[minmax(24rem,0.66fr)_minmax(0,1.25fr)_17rem] ' +
  'max-[720px]:grid-cols-1';

const IDEA_RANK_LIST_CLASSES =
  'idea-rank-list m-0 grid content-start gap-[0.7rem] overflow-y-auto ' +
  'border-r border-cosci-idea-list-border bg-transparent py-5 pr-6 ' +
  'pl-5 list-none';

// Single column: the rank + Elo chips sit on a top row (see
// IDEA_RANK_HEAD_CLASSES) and the title/preview run full width beneath them, so
// the text is not indented under a rank column.
const IDEA_RANK_ROW_CLASSES =
  'idea-rank-row grid min-h-[8.9rem] w-full cursor-pointer content-start ' +
  'gap-[0.5rem] rounded-[10px] ' +
  'border border-cosci-idea-row-border bg-cosci-idea-row-bg ' +
  'p-4 text-left text-cosci-idea-row-text transition-colors duration-150 ' +
  'hover:border-cosci-idea-row-hover-border ' +
  'hover:bg-cosci-idea-row-hover-bg ' +
  'motion-reduce:transition-none';

const IDEA_RANK_HEAD_CLASSES = 'idea-rank-head flex items-center gap-[0.6rem]';

const IDEA_RANK_SELECTED_CLASSES =
  'selected !border-cosci-idea-row-selected-border ' +
  '!bg-cosci-idea-row-selected-bg ' +
  'hover:!border-cosci-idea-row-selected-border ' +
  'hover:!bg-cosci-idea-row-selected-hover-bg';

const IDEA_CHIP_CLASSES =
  'inline-grid h-7 min-w-7 place-items-center rounded-full border-0 ' +
  'px-3 bg-cosci-idea-chip-bg text-[0.875rem] font-normal ' +
  'text-cosci-idea-chip-text';

const IDEA_ELO_CHIP_CLASSES = `${IDEA_CHIP_CLASSES} idea-elo-chip w-fit min-w-[6.35rem]`;

const IDEA_RANK_TITLE_CLASSES =
  'idea-rank-title mt-[0.35rem] block overflow-hidden text-ellipsis ' +
  'whitespace-nowrap text-base leading-6 font-medium ' +
  'text-cosci-idea-title-text';

const IDEA_RANK_PREVIEW_CLASSES =
  'idea-rank-preview line-clamp-2 overflow-hidden ' +
  'text-[0.75rem] leading-4 tracking-[0.1px] text-cosci-idea-preview-text';

const IDEA_DETAIL_PANE_CLASSES =
  'idea-detail-pane grid min-w-0 content-start gap-[1.35rem] overflow-x-hidden ' +
  'overflow-y-auto border-r-0 bg-transparent px-7 pt-[1.45rem] pb-14';

const IDEA_DETAIL_EMPTY_CLASSES =
  `${IDEA_DETAIL_PANE_CLASSES} empty place-items-center text-center ` +
  'text-[var(--md-sys-color-on-surface-variant)]';

const IDEA_DETAIL_SECTION_CLASSES =
  'idea-detail-section grid gap-[0.45rem] border-t-0 pt-0 ' +
  '[&_h2]:m-0 [&_h2]:mb-2 [&_h2]:font-gsans [&_h2]:text-[2rem] ' +
  '[&_h2]:leading-10 [&_h2]:font-normal ' +
  '[&_h2]:text-cosci-idea-title-text [&_h3]:m-0 ' +
  '[&_h3]:text-base [&_h3]:font-semibold [&_h3]:normal-case ' +
  '[&_h3]:text-cosci-idea-title-text [&_p]:m-0 ' +
  '[&_p]:[overflow-wrap:anywhere] [&_p]:text-base ' +
  '[&_p]:leading-6 [&_p]:text-cosci-idea-detail-text';

const IDEA_SECTIONS_RAIL_CLASSES =
  'idea-sections-rail m-5 min-w-0 min-w-[12.5rem] self-start ' +
  'rounded-[10px] bg-cosci-panel p-5 max-[720px]:hidden';

const IDEA_SECTIONS_LABEL_CLASSES =
  'text-[0.9rem] tracking-[0.1px] text-cosci-idea-title-text';

// Reference: ul with 20px above the first link, then li+li margin-top 24px.
const IDEA_SECTIONS_LIST_CLASSES = 'mt-5 grid gap-6';

// Slightly smaller than the body so the longest link ("Tournament
// performance >") fits on one line without widening the rail.
const IDEA_SECTION_LINK_CLASSES =
  'block whitespace-nowrap text-[0.85rem] leading-6 font-medium ' +
  'text-cosci-blue no-underline';

/**
 * Renders generated hypotheses in the Google-style split-pane pattern.
 *
 * @param props The hypotheses, reviews, and matches.
 */
export function IdeasTab({
  hypotheses,
  reviews,
  matches = [],
}: {
  hypotheses: Hypothesis[];
  reviews: Review[];
  matches?: MatchRow[];
}) {
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
      <EmptyState>
        Hypotheses appear here once the generation node runs.
      </EmptyState>
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
        <span className={IDEA_RANK_HEAD_CLASSES}>
          <span className={`idea-rank-number ${IDEA_CHIP_CLASSES}`}>
            {rank}
          </span>
          <span className={IDEA_ELO_CHIP_CLASSES}>
            Elo rating: {hypothesis.elo_rating}
          </span>
        </span>
        <span className={IDEA_RANK_TITLE_CLASSES}>{hypothesis.title}</span>
        <span className={IDEA_RANK_PREVIEW_CLASSES}>
          {hypothesis.statement}
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
        <Icon aria-hidden="true" name="format_list_numbered" />
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
            ? `${hypothesis.win_count} wins and ${hypothesis.loss_count} losses across ${totalMatches} pairwise matches (${Math.round(
                (hypothesis.win_count / totalMatches) * 100,
              )}% win rate).`
            : 'No tournament matches have been recorded yet.'}
        </p>
      </DetailSection>

      <DetailSection title="Match summary" level={2}>
        {latestMatch?.tier && (
          <p>
            <strong>Outcome:</strong>{' '}
            <span className="capitalize">{latestMatch.tier}</span>
          </p>
        )}
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
      <nav className={IDEA_SECTIONS_LIST_CLASSES}>
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
      </nav>
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
