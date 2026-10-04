import type {ClaimEvidenceRow, Hypothesis, MatchRow, Review} from '@/api/runs';
import {Icon} from '@/components/icon';
import {
  UNDERMINED_VERDICT,
  presentedHypotheses,
  ratingLabel,
  sortByEloDesc,
} from '@/lib/hypotheses';
import {useMemo} from 'react';
import {Link, useSearchParams} from 'react-router-dom';
import {useIsMobile} from '../../hooks/dom';
import {TruncatedLabel} from '../truncated_label';
import {
  DETAIL_PANE_ID,
  HypothesisDetail,
  SectionsRail,
} from './ideas_detail_pane';

const IDEA_SPLIT_SHELL_CLASSES =
  'idea-split-shell flex h-full min-h-0 flex-col overflow-hidden ' +
  'rounded-none border-0 bg-cosci-bg';

// Three-column fit and phone interaction need separate breakpoints; Tailwind
// requires literal responsive classes rather than dynamically assembled strings.
const IDEAS_REPORT_CLASSES =
  'flex h-full min-h-0 flex-col overflow-hidden bg-cosci-bg ' +
  'max-[1023px]:h-auto max-[1023px]:overflow-visible';

const IDEA_SPLIT_GRID_CLASSES =
  'idea-split-grid reference grid min-h-0 min-w-0 flex-1 ' +
  'grid-cols-[minmax(24rem,0.66fr)_minmax(0,1.25fr)_17rem] ' +
  'max-[1023px]:grid-cols-1';

// An auto grid track follows nowrap content width; minmax(0,1fr) prevents
// clipped cards and sideways scrolling.
const IDEA_RANK_LIST_CLASSES =
  'idea-rank-list m-0 grid min-w-0 grid-cols-[minmax(0,1fr)] content-start ' +
  'gap-[0.7rem] overflow-x-hidden overflow-y-auto ' +
  'border-r border-cosci-idea-list-border bg-transparent py-5 pr-6 ' +
  'pl-5 list-none';

const IDEA_RANK_ROW_CLASSES =
  'idea-rank-row grid min-h-[8.9rem] w-full min-w-0 ' +
  'grid-cols-[minmax(0,1fr)] cursor-pointer content-start ' +
  'gap-[0.5rem] rounded-[10px] no-underline ' +
  'border border-cosci-idea-row-border bg-cosci-idea-row-bg ' +
  'p-4 text-left text-cosci-idea-row-text transition-colors duration-150 ' +
  'hover:border-cosci-idea-row-hover-border ' +
  'hover:bg-cosci-idea-row-hover-bg ' +
  'motion-reduce:transition-none';

const IDEA_RANK_HEAD_CLASSES =
  'idea-rank-head flex min-w-0 flex-nowrap items-center gap-[0.6rem] ' +
  'overflow-hidden';

const IDEA_RANK_SELECTED_CLASSES =
  'selected !border-cosci-idea-row-selected-border ' +
  '!bg-cosci-idea-row-selected-bg ' +
  'hover:!border-cosci-idea-row-selected-border ' +
  'hover:!bg-cosci-idea-row-selected-hover-bg';

const IDEA_CHIP_CLASSES =
  'inline-grid h-7 min-w-7 place-items-center rounded-full border-0 ' +
  'px-3 bg-cosci-idea-chip-bg text-[0.875rem] font-normal ' +
  'whitespace-nowrap text-cosci-idea-chip-text';

const IDEA_ELO_CHIP_CLASSES =
  IDEA_CHIP_CLASSES + ' idea-elo-chip w-fit min-w-[6.35rem]';

const IDEA_UNVERIFIED_CHIP_CLASSES =
  'idea-unverified-chip inline-flex h-7 w-fit items-center gap-1 ' +
  'whitespace-nowrap ' +
  'rounded-full bg-cosci-idea-chip-bg px-3 text-[0.8rem] font-medium ' +
  'text-cosci-idea-chip-text';

// Undermined means evidence against an assumption; unverified means no verdict.
// Distinct caution tones must not imply equal scientific standing.
const IDEA_UNDERMINED_CHIP_CLASSES =
  'idea-undermined-chip inline-flex h-7 w-fit items-center gap-1 ' +
  'whitespace-nowrap ' +
  'rounded-full bg-th-destructive-container px-3 text-[0.8rem] ' +
  'font-medium text-th-destructive-on-container';

const IDEA_RANK_TITLE_CLASSES =
  'idea-rank-title mt-[0.35rem] block min-w-0 overflow-hidden ' +
  'whitespace-nowrap text-base leading-6 font-medium ' +
  'text-cosci-idea-title-text';

const IDEA_RANK_PREVIEW_CLASSES =
  'idea-rank-preview line-clamp-2 overflow-hidden ' +
  'text-[0.75rem] leading-4 tracking-[0.1px] text-cosci-idea-preview-text';

const IDEA_MOBILE_BACK_HINT_CLASSES = 'sr-only';

const IDEA_MOBILE_VIEW_CLASSES =
  'idea-mobile-view flex h-auto min-h-0 flex-none flex-col ' +
  'overflow-visible bg-cosci-bg';

const IDEA_MOBILE_LIST_CLASSES =
  'idea-mobile-list m-0 grid min-h-0 content-start gap-[0.7rem] ' +
  'overflow-visible bg-transparent p-4 list-none';

function resolveSelectedHypothesis(
  sorted: Hypothesis[],
  selectedId: string | null,
  isMobile: boolean,
): Hypothesis | null {
  if (!sorted.length) return null;
  if (selectedId) return sorted.find(h => h.id === selectedId) ?? sorted[0];
  return isMobile ? null : sorted[0];
}

function ideaSearch(id: string): {search: string} {
  return {search: `?idea=${encodeURIComponent(id)}`};
}

function useIdeaSelection(hypotheses: Hypothesis[], isMobile: boolean) {
  // Tab links omit selection search, so returning to the mobile ideas tab
  // reopens the list.
  const [params] = useSearchParams();
  const selectedId = params.get('idea');
  // Exclude withdrawn ideas before selecting defaults so hidden rows cannot
  // remain the selected detail.
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

// not one empty result.
function emptyIdeasNote(exploredCount: number): string {
  if (!exploredCount) {
    return 'Hypotheses appear here once the generation node runs.';
  }
  return (
    'Every idea this run explored was ruled out or folded into another. ' +
    'Nothing was put forward.'
  );
}

export function IdeasTab({
  hypotheses,
  reviews,
  matches = [],
  claimEvidence = [],
}: {
  runId?: string;
  isDemo?: boolean;
  hypotheses: Hypothesis[];
  reviews: Review[];
  matches?: MatchRow[];
  claimEvidence?: ClaimEvidenceRow[];
}) {
  const isMobile = useIsMobile();
  const {sorted, selected} = useIdeaSelection(hypotheses, isMobile);

  if (!sorted.length) {
    return (
      <div className="rounded border border-th-border p-6 text-sm text-center text-th-muted-fg">
        {emptyIdeasNote(hypotheses.length)}
      </div>
    );
  }

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

interface IdeaViewProps {
  sorted: Hypothesis[];
  selected: Hypothesis | null;
  reviews: Review[];
  matches: MatchRow[];
  claimEvidence: ClaimEvidenceRow[];
  runId?: string;
  isDemo?: boolean;
}

// The titlebar supplies the visible mobile Back control; this local screen-
// reader hint makes the escape discoverable inside the view.
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

function ideaRowClassName(selected: boolean): string {
  return selected
    ? `${IDEA_RANK_ROW_CLASSES} ${IDEA_RANK_SELECTED_CLASSES}`
    : IDEA_RANK_ROW_CLASSES;
}

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
      {hypothesis.unverified &&
      hypothesis.verification_verdict !== UNDERMINED_VERDICT ? (
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
      {/* Keep push navigation: mobile Back must return to the ranked list. */}
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
