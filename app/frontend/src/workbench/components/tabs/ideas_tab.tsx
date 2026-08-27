import {useMemo} from 'react';
import {Link, useSearchParams} from 'react-router-dom';
import type {ClaimEvidenceRow, Hypothesis, MatchRow, Review} from '@/api/runs';
import {
  UNDERMINED_VERDICT,
  presentedHypotheses,
  ratingLabel,
  sortByEloDesc,
} from '@/lib/hypotheses';
import {Icon} from '@/components/icon';
import {useIsMobile} from '../../hooks/use_is_mobile';
import {TruncatedLabel} from '../truncated_label';
import {EmptyState} from '../empty_state';
import {
  DETAIL_PANE_ID,
  HypothesisDetail,
  SectionsRail,
} from './ideas_detail_pane';

const IDEA_SPLIT_SHELL_CLASSES =
  'idea-split-shell flex h-full min-h-0 flex-col overflow-hidden ' +
  'rounded-none border-0 bg-cosci-bg';

// The three-column split has a hard, non-shrinkable floor: a 24rem (384px)
// ranked list plus a 17rem (272px) sections rail, so the detail column --
// the one the reader is actually here for -- gets whatever is left. Measured
// in a browser: 0px at a 701px viewport, 56px at 721px, 172px at 900px, and
// only 296px at 1024px. Below roughly 1024 the split therefore cannot render
// its own content, so the columns stack instead. This is deliberately NOT
// the phone breakpoint (`MOBILE_MEDIA_QUERY`, 700px): that one chooses
// between two interaction models (master-detail on a phone versus the split
// pane), while this one is a pure question of whether three columns fit.
// One number cannot answer both, and using the phone value for both is what
// left the 701-1023 band rendering an unreadable sliver.
//
// The `max-[1023px]:` variants below are written out in full on purpose:
// Tailwind scans source for literal class strings, so building them from a
// shared constant would compile to no CSS at all and silently restore the
// broken layout.
const IDEAS_REPORT_CLASSES =
  'flex h-full min-h-0 flex-col overflow-hidden bg-cosci-bg ' +
  'max-[1023px]:h-auto max-[1023px]:overflow-visible';

const IDEA_SPLIT_GRID_CLASSES =
  'idea-split-grid reference grid min-h-0 min-w-0 flex-1 ' +
  'grid-cols-[minmax(24rem,0.66fr)_minmax(0,1.25fr)_17rem] ' +
  'max-[1023px]:grid-cols-1';

const IDEA_RANK_LIST_CLASSES =
  'idea-rank-list m-0 grid content-start gap-[0.7rem] overflow-y-auto ' +
  'border-r border-cosci-idea-list-border bg-transparent py-5 pr-6 ' +
  'pl-5 list-none';

// Single column: the rank + Elo chips sit on a top row (see
// IDEA_RANK_HEAD_CLASSES) and the title/preview run full width beneath them, so
// the text is not indented under a rank column. The row is an anchor (each
// idea has its own ?idea= URL), hence the explicit no-underline.
const IDEA_RANK_ROW_CLASSES =
  'idea-rank-row grid min-h-[8.9rem] w-full cursor-pointer content-start ' +
  'gap-[0.5rem] rounded-[10px] no-underline ' +
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

// Caution chip for an idea with no evidence-supported claim: it is still ranked
// and published, but flagged so the reader treats it as unverified.
const IDEA_UNVERIFIED_CHIP_CLASSES =
  'idea-unverified-chip inline-flex h-7 w-fit items-center gap-1 ' +
  'rounded-full bg-cosci-idea-chip-bg px-3 text-[0.8rem] font-medium ' +
  'text-cosci-idea-chip-text';

// The stronger caution: deep verification probed a fundamental assumption of
// this idea and found it false. Wears the error tone rather than the neutral
// chip tone -- "Unverified" means nothing was found either way, this means
// something was found against it, and one shared look would flatten the two.
// The idea is still listed (it sorts below every sound one); the chip is what
// stops it reading as sound.
const IDEA_UNDERMINED_CHIP_CLASSES =
  'idea-undermined-chip inline-flex h-7 w-fit items-center gap-1 ' +
  'rounded-full bg-th-destructive-container px-3 text-[0.8rem] ' +
  'font-medium text-th-destructive-on-container';

const IDEA_RANK_TITLE_CLASSES =
  'idea-rank-title mt-[0.35rem] block min-w-0 overflow-hidden ' +
  'whitespace-nowrap text-base leading-6 font-medium ' +
  'text-cosci-idea-title-text';

const IDEA_RANK_PREVIEW_CLASSES =
  'idea-rank-preview line-clamp-2 overflow-hidden ' +
  'text-[0.75rem] leading-4 tracking-[0.1px] text-cosci-idea-preview-text';

// Mobile master-detail: the ideas tab is a plain list that swaps to a single
// idea's detail on tap (rather than the desktop split view). Visually hidden
// so it reaches only assistive technology -- the titlebar arrow itself is
// the one visible back control (see IDEA_MOBILE_BACK_HINT_CLASSES below).
const IDEA_MOBILE_BACK_HINT_CLASSES = 'sr-only';

const IDEA_MOBILE_VIEW_CLASSES =
  'idea-mobile-view flex h-auto min-h-0 flex-none flex-col ' +
  'overflow-visible bg-cosci-bg';

const IDEA_MOBILE_LIST_CLASSES =
  'idea-mobile-list m-0 grid min-h-0 content-start gap-[0.7rem] ' +
  'overflow-visible bg-transparent p-4 list-none';

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

// The route of one idea: the selection lives in the query string so a
// single idea can be linked to, opened in a new tab, and shared. Only the
// search part is set, so the link stays on whatever run/tab path it is
// rendered under.
function ideaSearch(id: string): {search: string} {
  return {search: `?idea=${encodeURIComponent(id)}`};
}

// Elo-ranked hypothesis list plus the currently selected one, keyed off
// whichever layout (mobile vs. desktop) is active. `sorted` mirrors the
// research-overview tab's "Winning ideas" ordering via the same
// sortByEloDesc helper.
function useIdeaSelection(hypotheses: Hypothesis[], isMobile: boolean) {
  // Explicitly selected hypothesis id (?idea=); absent means "use the
  // default" - see resolveSelectedHypothesis for what that resolves to. The
  // tab links carry no search, so leaving the tab drops the param and the
  // mobile master-detail view reopens on the list.
  const [params] = useSearchParams();
  const selectedId = params.get('idea');
  // Filtered before sorting, so a withdrawn idea can be neither listed nor
  // resolved as the default selection.
  const sorted = useMemo(
    () => sortByEloDesc(presentedHypotheses(hypotheses)),
    [hypotheses],
  );
  const selected = useMemo(
    () => resolveSelectedHypothesis(sorted, selectedId, isMobile),
    [sorted, selectedId, isMobile],
  );

  return {sorted, selected};
}

// Two different empty states: nothing generated yet, versus everything
// generated having been deduplicated or ruled out. Reporting the second as
// the first would read as a run that produced nothing at all.
function emptyIdeasNote(exploredCount: number): string {
  if (!exploredCount) {
    return 'Hypotheses appear here once the generation node runs.';
  }
  return (
    'Every idea this run explored was ruled out or folded into another. ' +
    'Nothing was put forward.'
  );
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
  const {sorted, selected} = useIdeaSelection(hypotheses, isMobile);

  if (!sorted.length) {
    return <EmptyState>{emptyIdeasNote(hypotheses.length)}</EmptyState>;
  }

  // Both views share the exact same prop shape, so the layout choice is just
  // which component to render.
  const IdeaView = isMobile ? MobileIdeaView : DesktopIdeaSplit;
  return (
    <div className={IDEAS_REPORT_CLASSES}>
      <IdeaView
        sorted={sorted}
        selected={selected}
        reviews={reviews}
        matches={matches}
        claimEvidence={claimEvidence}
      />
    </div>
  );
}

// The mobile and desktop idea views are interchangeable (IdeasTab picks one by
// viewport), so they share one prop shape.
interface IdeaViewProps {
  sorted: Hypothesis[];
  selected: Hypothesis | null;
  reviews: Review[];
  matches: MatchRow[];
  claimEvidence: ClaimEvidenceRow[];
}

// Master-detail: the list swaps to a single idea on tap. This view renders no
// back control of its own; the visible escape is the titlebar's Back arrow,
// which run_detail_shell.tsx's reportBackTarget retargets to the ranked list
// while an idea is open here (a sighted reader sees that arrow regardless).
// The sr-only hint below makes that relationship discoverable from inside
// the view itself, since nothing else here says so. The browser's own back
// gesture (each idea is a URL) and re-tapping the "All Ideas" tab (whose
// link carries no ?idea= param) still work as further escapes.
function MobileIdeaView({
  sorted,
  selected,
  reviews,
  matches,
  claimEvidence,
}: IdeaViewProps) {
  return (
    <div className={IDEA_MOBILE_VIEW_CLASSES}>
      {selected ? (
        <>
          <p className={IDEA_MOBILE_BACK_HINT_CLASSES}>
            Use the Back button in the title bar to return to the ranked ideas
            list.
          </p>
          <HypothesisDetail
            hypothesis={selected}
            reviews={reviews}
            matches={matches}
            claimEvidence={claimEvidence}
          />
        </>
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
}: IdeaViewProps) {
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
// The rank/Elo/caution chip row heading one idea in the list.
//
// An idea with no matches shows why it has no rating rather than the rating
// itself. Elo 1200 is where every hypothesis starts, so printing it for an
// idea that never played reads as a result it earned; and "Disqualified" and
// "Unranked" are different enough facts that one shared label for both
// misleads (see ratingLabel).
//
// The two caution chips can both appear, and say different things:
// "Undermined" is evidence found against the idea, "Unverified" is no
// supporting evidence found for it. Undermined comes first because it is
// the stronger claim.
function IdeaRankHead({
  rank,
  hypothesis,
}: {
  rank: number;
  hypothesis: Hypothesis;
}) {
  return (
    <span className={IDEA_RANK_HEAD_CLASSES}>
      <span className={`idea-rank-number ${IDEA_CHIP_CLASSES}`}>{rank}</span>
      <span className={IDEA_ELO_CHIP_CLASSES}>{ratingLabel(hypothesis)}</span>
      {hypothesis.verification_verdict === UNDERMINED_VERDICT ? (
        <span className={IDEA_UNDERMINED_CHIP_CLASSES}>
          <Icon aria-hidden="true" name="warning" />
          Undermined
        </span>
      ) : null}
      {hypothesis.unverified ? (
        <span className={IDEA_UNVERIFIED_CHIP_CLASSES}>
          <Icon aria-hidden="true" name="warning" />
          Unverified
        </span>
      ) : null}
    </span>
  );
}

function IdeaListItem({
  rank,
  hypothesis,
  selected,
}: {
  rank: number;
  hypothesis: Hypothesis;
  selected: boolean;
}) {
  return (
    <li>
      {/* No `replace`: on mobile the list is the previous entry, so the
          browser's back gesture returns to it. A real navigation link to a
          page-within-a-page, exactly like the report tab strip, so the
          selected row carries `aria-current="page"` (not the vaguer "true")
          plus `aria-controls` naming the detail pane it drives -- the
          relationship a listbox/option pair would otherwise imply, without
          taking on that widget's keyboard contract. */}
      <Link
        to={ideaSearch(hypothesis.id)}
        className={ideaRowClassName(selected)}
        aria-current={selected ? 'page' : undefined}
        aria-controls={selected ? DETAIL_PANE_ID : undefined}
      >
        <IdeaRankHead rank={rank} hypothesis={hypothesis} />
        <TruncatedLabel
          className={IDEA_RANK_TITLE_CLASSES}
          text={hypothesis.title}
        />
        <TruncatedLabel
          className={IDEA_RANK_PREVIEW_CLASSES}
          text={hypothesis.statement}
          lines={2}
        />
      </Link>
    </li>
  );
}
