import type {MouseEvent, ReactNode} from 'react';
import {useMemo, useState} from 'react';
import type {
  CitationRow,
  Hypothesis,
  MatchRow,
  Report,
  Review,
} from '@/api/runs';
import {Icon} from '@/components/icon';
import {smoothScrollToSection} from '@/lib/smooth_scroll';
import {EmptyState} from '../empty_state';

// Elo every hypothesis starts at; ideas above it held or gained ground in the
// tournament and read as "high potential", those below it lost ground.
const BASELINE_ELO = 1200;

const IDEA_SPLIT_SHELL_CLASSES =
  'idea-split-shell flex h-full min-h-0 flex-col overflow-hidden ' +
  'rounded-none border-0 bg-cosci-bg';

const IDEA_INSIGHTS_BAND_CLASSES =
  'idea-insights-band shrink-0 grid gap-4 border-b border-cosci-idea-list-border ' +
  'px-6 pt-5 pb-5 max-[720px]:px-4';

const IDEA_INSIGHTS_CARD_CLASSES =
  'idea-insights-card rounded-xl border border-cosci-idea-insight-card-border ' +
  'bg-cosci-idea-insight-card-bg px-5 py-4';

const IDEA_INSIGHTS_HEADER_CLASSES =
  'idea-insights-header flex w-full items-center gap-2 border-0 bg-transparent ' +
  'p-0 text-left';

const IDEA_INSIGHTS_TITLE_CLASSES =
  'idea-insights-title text-[0.95rem] font-semibold ' +
  'text-cosci-idea-insight-title';

const IDEA_INSIGHTS_BODY_CLASSES =
  'idea-insights-body mt-3 text-[0.88rem] leading-[1.55] ' +
  'text-cosci-idea-insight-body [overflow-wrap:anywhere]';

const IDEA_STAT_ROW_CLASSES =
  'idea-stat-row grid grid-cols-4 gap-4 max-[720px]:grid-cols-2';

const IDEA_STAT_CARD_CLASSES =
  'idea-stat-card grid gap-2 rounded-xl border border-cosci-idea-stat-border ' +
  'bg-cosci-idea-stat-bg px-4 py-[0.9rem]';

const IDEA_STAT_LABEL_CLASSES =
  'idea-stat-label text-[0.78rem] leading-[1.3] text-cosci-idea-stat-label';

const IDEA_STAT_VALUE_CLASSES =
  'idea-stat-value text-[1.5rem] leading-none font-medium ' +
  'text-cosci-idea-stat-value';

const IDEA_SPLIT_GRID_CLASSES =
  'idea-split-grid reference grid min-h-0 min-w-0 flex-1 ' +
  'grid-cols-[minmax(24rem,0.66fr)_minmax(0,1.25fr)_17rem] ' +
  'max-[720px]:grid-cols-1';

const IDEA_RANK_LIST_CLASSES =
  'idea-rank-list m-0 grid content-start gap-[0.7rem] overflow-y-auto ' +
  'border-r border-cosci-idea-list-border bg-transparent py-5 pr-6 ' +
  'pl-5 list-none';

const IDEA_RANK_ROW_CLASSES =
  'idea-rank-row grid min-h-[8.9rem] w-full cursor-pointer ' +
  'grid-cols-[1.75rem_minmax(0,1fr)] items-start gap-[0.65rem] rounded-[10px] ' +
  'border border-cosci-idea-row-border bg-cosci-idea-row-bg ' +
  'p-4 text-left text-cosci-idea-row-text transition-colors duration-150 ' +
  'hover:border-cosci-idea-row-hover-border ' +
  'hover:bg-cosci-idea-row-hover-bg ' +
  'motion-reduce:transition-none';

const IDEA_RANK_SELECTED_CLASSES =
  'selected !border-cosci-idea-row-selected-border ' +
  '!bg-cosci-idea-row-selected-bg ' +
  'hover:!border-cosci-idea-row-selected-border ' +
  'hover:!bg-cosci-idea-row-selected-hover-bg';

const IDEA_CHIP_CLASSES =
  'inline-grid h-7 min-w-7 place-items-center rounded-full border-0 ' +
  'px-3 bg-cosci-idea-chip-bg text-[0.875rem] font-normal ' +
  'text-cosci-idea-chip-text';

const IDEA_ELO_CHIP_CLASSES = `${IDEA_CHIP_CLASSES} idea-elo-chip mb-3 w-fit min-w-[6.35rem]`;

const IDEA_RANK_CONTENT_CLASSES = 'idea-rank-content min-w-0';

const IDEA_RANK_TITLE_CLASSES =
  'idea-rank-title mt-[0.15rem] block overflow-hidden text-ellipsis ' +
  'whitespace-nowrap text-base leading-6 font-medium ' +
  'text-cosci-idea-title-text';

const IDEA_RANK_PREVIEW_CLASSES =
  'idea-rank-preview mt-[0.45rem] line-clamp-2 overflow-hidden ' +
  'text-[0.75rem] leading-4 tracking-[0.1px] text-cosci-idea-preview-text';

const IDEA_DETAIL_PANE_CLASSES =
  'idea-detail-pane grid min-w-0 content-start gap-[1.35rem] overflow-x-hidden ' +
  'overflow-y-auto border-r-0 bg-transparent px-7 pt-[1.45rem] pb-14';

const IDEA_DETAIL_EMPTY_CLASSES =
  `${IDEA_DETAIL_PANE_CLASSES} empty place-items-center text-center ` +
  'text-[var(--md-sys-color-on-surface-variant)]';

const IDEA_BREADCRUMB_CLASSES =
  'idea-breadcrumb inline-flex h-[1.65rem] min-h-[1.65rem] w-fit max-w-full ' +
  'items-center overflow-hidden rounded-[5px] bg-cosci-idea-breadcrumb-bg ' +
  'px-2 text-[0.6875rem] leading-[1.65rem] font-medium tracking-[0.1px] ' +
  'text-ellipsis whitespace-nowrap text-cosci-idea-breadcrumb-text';

const IDEA_BREADCRUMB_TEXT_CLASSES =
  'overflow-hidden text-ellipsis leading-[1.65rem]';

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
  'idea-sections-rail mt-5 mr-5 ml-2 grid min-w-0 self-start gap-5 ' +
  'rounded-[10px] bg-cosci-panel p-5 max-[720px]:hidden';

const IDEA_SECTIONS_LABEL_CLASSES =
  'text-[0.75rem] tracking-[0.1px] text-cosci-idea-title-text';

const IDEA_SECTION_LINK_CLASSES =
  'text-base leading-6 font-medium text-cosci-blue ' + 'no-underline';

/**
 * Renders generated hypotheses in the Google-style split-pane pattern.
 *
 * @param props The hypotheses, citations, reviews, and matches.
 */
export function IdeasTab({
  hypotheses,
  citations,
  reviews,
  matches = [],
  report = null,
}: {
  hypotheses: Hypothesis[];
  citations: CitationRow[];
  reviews: Review[];
  matches?: MatchRow[];
  report?: Report | null;
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const insights = useMemo(
    () => deriveInsights(hypotheses, citations, report),
    [hypotheses, citations, report],
  );

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
      <AgentInsights insights={insights} />
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

/** Synthesized counts and summary shown in the Agent Insights band. */
interface IdeaInsights {
  summary: string;
  highPotential: number;
  nonViable: number;
  verified: number;
  sourcesAnalyzed: number;
}

/**
 * Derives the Agent Insights band data from our own run artifacts.
 *
 * Mapping (documented for owner review):
 * - High potential: hypotheses strictly above the baseline Elo (gained ground
 *   in the tournament).
 * - Non-viable: hypotheses strictly below the baseline Elo (lost ground).
 * - Verified: distinct hypotheses backed by at least one 'verified' citation.
 * - Sources analyzed: distinct evidence sources referenced by any citation.
 *
 * @param hypotheses The run's hypotheses with Elo ratings.
 * @param citations The claim-to-evidence citations with their verify state.
 * @param report The run report, reused for the synthesized summary line.
 * @returns The counts and summary for the band.
 */
function deriveInsights(
  hypotheses: Hypothesis[],
  citations: CitationRow[],
  report: Report | null,
): IdeaInsights {
  // The two buckets are deliberately extremes, not a partition (per the
  // reference stat cards): high potential counts hypotheses strictly above the
  // tournament baseline and non-viable counts those strictly below. Ideas at
  // exactly the baseline — and any with a null/undefined Elo — fall into
  // neither bucket, so the counts need not sum to the total.
  let highPotential = 0;
  let nonViable = 0;
  for (const h of hypotheses) {
    if (h.elo_rating > BASELINE_ELO) highPotential += 1;
    else if (h.elo_rating < BASELINE_ELO) nonViable += 1;
  }

  const verifiedHypotheses = new Set<string>();
  const sources = new Set<string>();
  for (const c of citations) {
    sources.add(c.evidence_id);
    if (c.state === 'verified') verifiedHypotheses.add(c.hypothesis_id);
  }

  return {
    summary: buildSummary(report, hypotheses.length, highPotential),
    highPotential,
    nonViable,
    verified: verifiedHypotheses.size,
    sourcesAnalyzed: sources.size,
  };
}

/**
 * Reuses the research-overview summary when present, else derives a sentence.
 *
 * @param report The run report (may be null before synthesis completes).
 * @param total The total hypothesis count.
 * @param highPotential The count of above-baseline hypotheses.
 * @returns A synthesized summary paragraph for the band.
 */
function buildSummary(
  report: Report | null,
  total: number,
  highPotential: number,
): string {
  const overview = report?.payload.research_overview?.overview?.summary;
  if (overview && overview.trim()) return overview.trim();
  if (!total) {
    return 'Agent insights will appear here once the generation and ranking nodes have run.';
  }
  return (
    `The agents generated ${total} ${total === 1 ? 'hypothesis' : 'hypotheses'} and ranked them ` +
    `through pairwise tournaments, with ${highPotential} rising above the baseline as the ` +
    'most promising directions. Select any hypothesis to inspect its review and tournament record.'
  );
}

function AgentInsights({insights}: {insights: IdeaInsights}) {
  const [open, setOpen] = useState(true);
  const stats: {label: string; value: number}[] = [
    {label: 'High potential ideas', value: insights.highPotential},
    {label: 'Non-viable ideas', value: insights.nonViable},
    {label: 'Number of verified ideas', value: insights.verified},
    {label: 'Sources analyzed', value: insights.sourcesAnalyzed},
  ];
  return (
    <div className={IDEA_INSIGHTS_BAND_CLASSES}>
      <section
        className={IDEA_INSIGHTS_CARD_CLASSES}
        aria-label="Agent insights"
      >
        <button
          type="button"
          className={IDEA_INSIGHTS_HEADER_CLASSES}
          aria-expanded={open}
          onClick={() => setOpen(prev => !prev)}
        >
          <Icon
            name="stars"
            aria-hidden="true"
            className="h-5 w-5 shrink-0 text-cosci-idea-insight-icon"
          />
          <span className={IDEA_INSIGHTS_TITLE_CLASSES}>Agent Insights</span>
          <Icon
            name={open ? 'expand_less' : 'expand_more'}
            aria-hidden="true"
            className="ml-auto h-5 w-5 shrink-0 text-cosci-idea-insight-body"
          />
        </button>
        {open && (
          <p className={IDEA_INSIGHTS_BODY_CLASSES}>{insights.summary}</p>
        )}
      </section>
      <div className={IDEA_STAT_ROW_CLASSES}>
        {stats.map(stat => (
          <div key={stat.label} className={IDEA_STAT_CARD_CLASSES}>
            <span className={IDEA_STAT_LABEL_CLASSES}>{stat.label}</span>
            <span className={IDEA_STAT_VALUE_CLASSES}>{stat.value}</span>
          </div>
        ))}
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
      <div className={IDEA_BREADCRUMB_CLASSES}>
        <span className={IDEA_BREADCRUMB_TEXT_CLASSES}>
          Co-Scientist &gt; Ranked hypothesis &gt; {hypothesis.title}
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
