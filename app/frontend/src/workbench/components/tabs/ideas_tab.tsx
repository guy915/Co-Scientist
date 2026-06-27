import '@material/web/icon/icon.js';
import type {ReactNode} from 'react';
import {useMemo, useState} from 'react';
import type {CitationRow, Hypothesis, MatchRow, Review} from '@/api/runs';

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
    <div className="idea-split-shell wb-fade-in">
      <div className="idea-split-grid reference">
        <ol className="idea-rank-list" aria-label="Ranked hypothesis list">
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
        className={selected ? 'idea-rank-row selected' : 'idea-rank-row'}
        onClick={onSelect}
      >
        <span className="idea-rank-number">{rank}</span>
        <span className="idea-rank-content">
          <span className="idea-elo-chip">
            Elo rating: {hypothesis.elo_rating}
          </span>
          <span className="idea-rank-title">{hypothesis.title}</span>
          <span className="idea-rank-preview">{hypothesis.statement}</span>
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
      <section className="idea-detail-pane empty">
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
    <section className="idea-detail-pane" aria-label="Hypothesis detail">
      <div className="idea-breadcrumb">
        <span>
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
      className="idea-detail-section"
      id={title.toLowerCase().replaceAll(' ', '-')}
    >
      <Heading>{title}</Heading>
      <div>{children}</div>
    </section>
  );
}

function SectionsRail() {
  return (
    <aside className="idea-sections-rail" aria-label="Sections">
      <span>Sections</span>
      {[
        'Hypothesis overview',
        'Description',
        'Review summary',
        'Full review',
        'Tournament performance',
      ].map(item => (
        <a key={item} href={`#${item.toLowerCase().replaceAll(' ', '-')}`}>
          {item} &gt;
        </a>
      ))}
    </aside>
  );
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
