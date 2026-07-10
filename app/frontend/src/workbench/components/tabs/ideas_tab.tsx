import {useMemo, useState} from 'react';
import type {ClaimEvidenceRow, Hypothesis, MatchRow, Review} from '@/api/runs';
import {sortByEloDesc} from '@/lib/hypotheses';
import {useIsMobile} from '../../hooks/use_is_mobile';
import {TruncatedLabel} from '../truncated_label';
import {EmptyState} from '../empty_state';
import {HypothesisDetail, SectionsRail} from './ideas_detail_pane';

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

const IDEA_ELO_CHIP_CLASSES =
  IDEA_CHIP_CLASSES + ' idea-elo-chip w-fit min-w-[6.35rem]';

const IDEA_RANK_TITLE_CLASSES =
  'idea-rank-title mt-[0.35rem] block min-w-0 overflow-hidden ' +
  'whitespace-nowrap text-base leading-6 font-medium ' +
  'text-cosci-idea-title-text';

const IDEA_RANK_PREVIEW_CLASSES =
  'idea-rank-preview line-clamp-2 overflow-hidden ' +
  'text-[0.75rem] leading-4 tracking-[0.1px] text-cosci-idea-preview-text';

// Mobile master-detail: the ideas tab is a plain list that swaps to a single
// idea's detail on tap (rather than the desktop split view), with a back
// affordance to return to the list.
const IDEA_MOBILE_VIEW_CLASSES =
  'idea-mobile-view flex h-full min-h-0 flex-col overflow-hidden bg-cosci-bg';

const IDEA_MOBILE_LIST_CLASSES =
  'idea-mobile-list m-0 grid min-h-0 flex-1 content-start gap-[0.7rem] ' +
  'overflow-y-auto bg-transparent p-4 list-none';

// Default selection for the split/master-detail views: an explicit tap wins
// (falling back to the top idea if it no longer exists), otherwise desktop
// pre-selects the top idea while mobile opens on the bare list.
function resolveSelectedHypothesis(
  sorted: Hypothesis[],
  selectedId: string | null,
  isMobile: boolean,
): Hypothesis | null {
  if (!sorted.length) return null;
  if (selectedId) return sorted.find(h => h.id === selectedId) ?? sorted[0];
  return isMobile ? null : sorted[0];
}

// Elo-ranked hypothesis list plus the currently selected one, keyed off
// whichever layout (mobile vs. desktop) is active. `sorted` mirrors the
// research-overview tab's "Winning ideas" ordering via the same
// sortByEloDesc helper.
function useIdeaSelection(hypotheses: Hypothesis[], isMobile: boolean) {
  // Explicitly selected hypothesis id (set by tapping a row); null means "use
  // the default" - see resolveSelectedHypothesis for what that resolves to.
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const sorted = useMemo(() => sortByEloDesc(hypotheses), [hypotheses]);
  const selected = useMemo(
    () => resolveSelectedHypothesis(sorted, selectedId, isMobile),
    [sorted, selectedId, isMobile],
  );

  return {sorted, selected, onSelect: setSelectedId};
}

/**
 * Renders generated hypotheses in the Google-style split-pane pattern.
 *
 * @param props The hypotheses, reviews, matches, and claim-evidence graph.
 */
export function IdeasTab({
  hypotheses,
  reviews,
  matches = [],
  claimEvidence = [],
}: {
  hypotheses: Hypothesis[];
  reviews: Review[];
  matches?: MatchRow[];
  claimEvidence?: ClaimEvidenceRow[];
}) {
  const isMobile = useIsMobile();
  const {sorted, selected, onSelect} = useIdeaSelection(hypotheses, isMobile);

  if (!hypotheses.length) {
    return (
      <EmptyState>
        Hypotheses appear here once the generation node runs.
      </EmptyState>
    );
  }

  // Both views share the exact same prop shape, so the layout choice is just
  // which component to render.
  const IdeaView = isMobile ? MobileIdeaView : DesktopIdeaSplit;
  return (
    <IdeaView
      sorted={sorted}
      selected={selected}
      reviews={reviews}
      matches={matches}
      claimEvidence={claimEvidence}
      onSelect={onSelect}
    />
  );
}

// Master-detail: the list swaps to a single idea on tap. There is no back
// affordance here — the user returns to the list by tapping the "All Ideas"
// tab, which remounts this view (see RunDetail's tab handler).
function MobileIdeaView({
  sorted,
  selected,
  reviews,
  matches,
  claimEvidence,
  onSelect,
}: {
  sorted: Hypothesis[];
  selected: Hypothesis | null;
  reviews: Review[];
  matches: MatchRow[];
  claimEvidence: ClaimEvidenceRow[];
  onSelect: (id: string) => void;
}) {
  return (
    <div className={IDEA_MOBILE_VIEW_CLASSES}>
      {selected ? (
        <HypothesisDetail
          hypothesis={selected}
          reviews={reviews}
          matches={matches}
          claimEvidence={claimEvidence}
        />
      ) : (
        <ol
          className={IDEA_MOBILE_LIST_CLASSES}
          aria-label="Ranked hypothesis list"
        >
          {sorted.map((h, index) => (
            <IdeaListItem
              key={h.id}
              rank={index + 1}
              hypothesis={h}
              selected={false}
              onSelect={() => onSelect(h.id)}
            />
          ))}
        </ol>
      )}
    </div>
  );
}

// Desktop split view: ranked list, detail pane, and the jump-to-section rail.
function DesktopIdeaSplit({
  sorted,
  selected,
  reviews,
  matches,
  claimEvidence,
  onSelect,
}: {
  sorted: Hypothesis[];
  selected: Hypothesis | null;
  reviews: Review[];
  matches: MatchRow[];
  claimEvidence: ClaimEvidenceRow[];
  onSelect: (id: string) => void;
}) {
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
              onSelect={() => onSelect(h.id)}
            />
          ))}
        </ol>
        <HypothesisDetail
          hypothesis={selected}
          reviews={reviews}
          matches={matches}
          claimEvidence={claimEvidence}
        />
        <SectionsRail />
      </div>
    </div>
  );
}

// Picks the selected vs. unselected idea-row class variant.
function ideaRowClassName(selected: boolean): string {
  return selected
    ? `${IDEA_RANK_ROW_CLASSES} ${IDEA_RANK_SELECTED_CLASSES}`
    : IDEA_RANK_ROW_CLASSES;
}

// A single row in the ranked hypothesis list: rank badge, Elo chip, title,
// and a truncated statement preview.
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
        className={ideaRowClassName(selected)}
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
        <TruncatedLabel
          className={IDEA_RANK_TITLE_CLASSES}
          text={hypothesis.title}
        />
        <TruncatedLabel
          className={IDEA_RANK_PREVIEW_CLASSES}
          text={hypothesis.statement}
          lines={2}
        />
      </button>
    </li>
  );
}
