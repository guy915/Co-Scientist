import '@material/web/icon/icon.js';
import '@material/web/chips/chip-set.js';
import '@material/web/chips/filter-chip.js';
import {useMemo, useState} from 'react';
import type {CitationRow, Hypothesis, Review} from '@/api/runs';
import {useT} from '@/i18n';

type SortKey = 'elo' | 'title' | 'generation';
type FilterKey = 'all' | 'initial' | 'evolved';

/**
 * Renders the sortable, filterable list of generated hypotheses.
 *
 * @param props The hypotheses, their citations and reviews, and a focus
 *   handler invoked when a row is opened in detail.
 */
export function IdeasTab({
  hypotheses,
  citations,
  reviews,
  onFocus,
}: {
  hypotheses: Hypothesis[];
  citations: CitationRow[];
  reviews: Review[];
  onFocus: (id: string) => void;
}) {
  const t = useT();
  const [filter, setFilter] = useState<FilterKey>('all');
  const [sortKey, setSortKey] = useState<SortKey>('elo');

  const filterLabel: Record<FilterKey, string> = {
    all: t('status.all'),
    initial: t('ideas.filter.initial'),
    evolved: t('ideas.filter.evolved'),
  };
  const sortLabel: Record<SortKey, string> = {
    elo: t('label.elo'),
    title: t('ideas.sort.title'),
    generation: t('ideas.sort.generation'),
  };

  const sorted = useMemo(() => {
    const arr = [...hypotheses];
    arr.sort((a, b) => {
      if (sortKey === 'elo') return b.elo_rating - a.elo_rating;
      if (sortKey === 'title') return a.title.localeCompare(b.title);
      return a.generation - b.generation || b.elo_rating - a.elo_rating;
    });
    return arr;
  }, [hypotheses, sortKey]);

  const filtered = useMemo(
    () =>
      sorted.filter(h => {
        if (filter === 'initial') return !h.parent_id;
        if (filter === 'evolved') return !!h.parent_id;
        return true;
      }),
    [sorted, filter],
  );

  if (!hypotheses.length) {
    return <Empty msg={t('ideas.empty')} />;
  }

  return (
    <div className="space-y-3 wb-fade-in">
      <div className="grid gap-2 text-sm sm:flex sm:flex-wrap sm:items-center">
        <div className="flex min-w-0 items-center gap-2">
          <span
            className="shrink-0"
            style={{color: 'var(--md-sys-color-on-surface-variant)'}}
          >
            {t('action.filter')}
          </span>
          <md-chip-set>
            {(['all', 'initial', 'evolved'] as FilterKey[]).map(f => (
              <md-filter-chip
                key={f}
                selected={filter === f || undefined}
                onclick={(() => setFilter(f)) as EventListener}
              >
                {filterLabel[f]}
              </md-filter-chip>
            ))}
          </md-chip-set>
        </div>
        <div className="flex min-w-0 items-center gap-2">
          <span
            className="shrink-0"
            style={{color: 'var(--md-sys-color-on-surface-variant)'}}
          >
            {t('action.sort')}
          </span>
          <md-chip-set>
            {(['elo', 'title', 'generation'] as SortKey[]).map(k => (
              <md-filter-chip
                key={k}
                selected={sortKey === k || undefined}
                onclick={(() => setSortKey(k)) as EventListener}
              >
                {sortLabel[k]}
              </md-filter-chip>
            ))}
          </md-chip-set>
        </div>
      </div>
      <ol className="space-y-2">
        {filtered.map((h, i) => (
          <IdeaRow
            key={h.id}
            rank={i + 1}
            h={h}
            citations={citations.filter(c => c.hypothesis_id === h.id)}
            reviews={reviews.filter(r => r.hypothesis_id === h.id)}
            onClick={() => onFocus(h.id)}
          />
        ))}
      </ol>
    </div>
  );
}

function IdeaRow({
  rank,
  h,
  citations,
  reviews,
  onClick,
}: {
  rank: number;
  h: Hypothesis;
  citations: CitationRow[];
  reviews: Review[];
  onClick: () => void;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const verified = citations.filter(c => c.state === 'verified').length;
  const totalCit = citations.length;
  const totalMatches = h.win_count + h.loss_count;
  const winRate = totalMatches
    ? Math.round((h.win_count / totalMatches) * 100)
    : null;

  return (
    <li
      className="rounded border transition-colors hover:bg-[color:var(--md-sys-color-secondary-container)]"
      style={{
        borderColor: 'var(--md-sys-color-outline-variant)',
        backgroundColor: 'var(--md-sys-color-surface-container-low)',
      }}
    >
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full text-left p-3 flex items-start gap-2 sm:gap-3"
      >
        <span
          className="text-xs font-mono mt-0.5 w-6 sm:w-7 text-right inline-flex items-center justify-end gap-0.5 shrink-0"
          style={{color: 'var(--md-sys-color-on-surface-variant)'}}
        >
          {open ? (
            <md-icon style={{fontSize: '14px'}}>keyboard_arrow_down</md-icon>
          ) : (
            <md-icon style={{fontSize: '14px'}}>keyboard_arrow_right</md-icon>
          )}
          {rank}
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium">{h.title}</span>
            <span
              className="text-xs px-1.5 py-0.5 rounded font-mono"
              style={{
                backgroundColor: 'var(--md-sys-color-secondary-container)',
                color: 'var(--md-sys-color-on-secondary-container)',
              }}
            >
              {t('ideas.badge.elo', {rating: h.elo_rating})}
            </span>
            {h.parent_id && (
              <span
                className="text-xs px-1.5 py-0.5 rounded"
                style={{
                  backgroundColor:
                    'color-mix(in srgb, var(--md-sys-color-tertiary) 18%, transparent)',
                }}
              >
                {t('ideas.badge.gen', {generation: h.generation})}
              </span>
            )}
            {winRate !== null && (
              <span
                className="text-xs px-1.5 py-0.5 rounded font-mono"
                title={t('ideas.badge.winLoss', {
                  wins: h.win_count,
                  losses: h.loss_count,
                })}
                style={{
                  backgroundColor:
                    'color-mix(in srgb, var(--md-sys-color-primary) 14%, transparent)',
                }}
              >
                {winRate}%
              </span>
            )}
            {totalCit > 0 && (
              <span
                className="text-xs"
                style={{color: 'var(--md-sys-color-on-surface-variant)'}}
              >
                {t('ideas.badge.verified', {
                  verified,
                  total: totalCit,
                })}
              </span>
            )}
          </div>
          {!open && (
            <p
              className="text-xs mt-1 line-clamp-2"
              style={{color: 'var(--md-sys-color-on-surface-variant)'}}
            >
              {h.statement}
            </p>
          )}
        </div>
      </button>
      {open && (
        <div
          className="px-3 pb-3 -mt-1 space-y-2 text-sm wb-fade-in"
          style={{color: 'var(--md-sys-color-on-surface)'}}
        >
          <p>{h.statement}</p>
          {h.mechanism && (
            <p>
              <strong>{t('ideas.field.mechanism')}</strong> {h.mechanism}
            </p>
          )}
          {h.expected_effect && (
            <p>
              <strong>{t('ideas.field.expectedEffect')}</strong>{' '}
              {h.expected_effect}
            </p>
          )}
          <div
            className="flex items-center gap-3 text-xs"
            style={{color: 'var(--md-sys-color-on-surface-variant)'}}
          >
            {reviews.length > 0 && (
              <span>
                {t(
                  reviews.length === 1
                    ? 'ideas.reviews.count'
                    : 'ideas.reviews.count_plural',
                  {count: reviews.length},
                )}
              </span>
            )}
            <button
              type="button"
              className="inline-flex items-center gap-1 underline underline-offset-2"
              onClick={e => {
                e.stopPropagation();
                onClick();
              }}
            >
              <md-icon style={{fontSize: '12px'}} aria-hidden="true">
                open_in_new
              </md-icon>{' '}
              {t('ideas.action.openDetail')}
            </button>
          </div>
        </div>
      )}
    </li>
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
