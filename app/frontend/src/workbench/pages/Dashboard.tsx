import '@material/web/icon/icon.js';
import '@material/web/button/filled-button.js';
import '@material/web/chips/chip-set.js';
import '@material/web/chips/filter-chip.js';
import '@material/web/textfield/outlined-text-field.js';

import {useEffect, useMemo, useState} from 'react';
import {Link, useNavigate} from 'react-router-dom';
import {
  getRun,
  getSystemStatus,
  listDemoRuns,
  listRuns,
  type Run,
  type RunStatus,
  type RunSummary,
  type SystemStatus,
} from '@/api/runs';
import {RunStatusPill} from '../components/RunStatusPill';
import {useT} from '@/i18n';
import type {TFunction} from '@/i18n';

function fmtDate(ts: number) {
  return new Date(ts * 1000).toLocaleString();
}

function fmtRelative(ts: number, t: TFunction) {
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return t('dashboard.time.justNow');
  if (diff < 3600)
    return t('dashboard.time.minutesAgo', {count: Math.floor(diff / 60)});
  if (diff < 86400)
    return t('dashboard.time.hoursAgo', {count: Math.floor(diff / 3600)});
  return t('dashboard.time.daysAgo', {count: Math.floor(diff / 86400)});
}

function formatModelName(rawName: string): string {
  if (!rawName) return '';
  const name = rawName.includes('/')
    ? rawName.split('/').slice(1).join('/')
    : rawName;
  const clean = name.replace(/[-_]/g, ' ');
  return clean
    .split(' ')
    .map(word => {
      if (!word) return '';
      const l = word.toLowerCase();
      if (l === 'gpt') return 'GPT';
      if (l === 'gemini') return 'Gemini';
      if (l === 'claude') return 'Claude';
      if (l === 'llama') return 'Llama';
      if (l === 'deepseek') return 'DeepSeek';
      if (l.match(/^v\d+$/)) return l.toUpperCase();
      return word.charAt(0).toUpperCase() + word.slice(1);
    })
    .join(' ');
}

type Filter = 'all' | RunStatus;

function filterLabel(f: Filter, t: TFunction): string {
  const map: Record<Filter, string> = {
    all: t('status.all'),
    draft: t('status.draft'),
    queued: t('status.queued'),
    running: t('status.running'),
    synthesizing: t('status.synthesizing'),
    completed: t('status.completed'),
    failed: t('status.failed'),
    blocked: t('status.blocked'),
    cancelled: t('status.cancelled'),
  };
  return map[f] ?? f;
}

/**
 * Renders the run dashboard with summary stats and the searchable run list.
 */
export function Dashboard() {
  const navigate = useNavigate();
  const t = useT();
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [summaries, setSummaries] = useState<Record<string, RunSummary>>({});
  const [demoRuns, setDemoRuns] = useState<Run[]>([]);
  const [demoSummaries, setDemoSummaries] = useState<
    Record<string, RunSummary>
  >({});
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState<Filter>('all');

  useEffect(() => {
    void getSystemStatus()
      .then(setSystemStatus)
      .catch(() => {});
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const r = await listRuns();
        if (cancelled) return;
        setRuns(r);
        // Fan-out the per-run summary fetches; tolerate failures.
        const entries = await Promise.allSettled(
          r.slice(0, 30).map(async run => {
            const detail = await getRun(run.id);
            return [run.id, detail.summary] as const;
          }),
        );
        if (cancelled) return;
        const map: Record<string, RunSummary> = {};
        for (const e of entries) {
          if (e.status === 'fulfilled') map[e.value[0]] = e.value[1];
        }
        setSummaries(map);

        const demos = await listDemoRuns();
        if (cancelled) return;
        setDemoRuns(demos);
        const demoEntries = await Promise.allSettled(
          demos.map(async run => {
            const detail = await getRun(run.id);
            return [run.id, detail.summary] as const;
          }),
        );
        if (cancelled) return;
        const demoMap: Record<string, RunSummary> = {};
        for (const e of demoEntries) {
          if (e.status === 'fulfilled') demoMap[e.value[0]] = e.value[1];
        }
        setDemoSummaries(demoMap);
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const filtered = useMemo(() => {
    if (!runs) return null;
    return [...runs, ...demoRuns].filter(r => {
      if (filter !== 'all' && r.status !== filter) return false;
      if (!query.trim()) return true;
      return r.research_goal.toLowerCase().includes(query.toLowerCase());
    });
  }, [runs, demoRuns, query, filter]);

  const totals = useMemo(() => {
    if (!runs) return null;
    return {
      total: runs.length,
      completed: runs.filter(r => r.status === 'completed').length,
      running: runs.filter(r =>
        ['running', 'queued', 'synthesizing'].includes(r.status),
      ).length,
      mock: runs.filter(r => r.provider === 'mock').length,
      hypotheses: Object.values(summaries).reduce(
        (acc, s) => acc + (s?.hypotheses ?? 0),
        0,
      ),
      matches: Object.values(summaries).reduce(
        (acc, s) => acc + (s?.matches ?? 0),
        0,
      ),
    };
  }, [runs, summaries]);

  return (
    <div className="space-y-6">
      <header className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="md-typescale-headline-medium text-2xl font-semibold tracking-tight">
            {t('dashboard.title')}
          </h1>
          <p
            className="text-sm"
            style={{color: 'var(--md-sys-color-on-surface-variant)'}}
          >
            {t('dashboard.subtitle')}
          </p>
        </div>
        <md-filled-button
          onclick={(() => navigate('/runs/new')) as EventListener}
        >
          <md-icon slot="icon" aria-hidden="true">
            add
          </md-icon>
          {t('action.newRun')}
        </md-filled-button>
      </header>

      {totals && (
        <section className="grid grid-cols-2 sm:grid-cols-4 gap-2 wb-fade-in">
          <StatCard
            label={t('dashboard.stat.totalRuns')}
            value={totals.total}
            sub={t('dashboard.stat.completedCount', {count: totals.completed})}
          />
          <StatCard
            label={t('status.active')}
            value={totals.running}
            sub={
              totals.running
                ? t('dashboard.stat.inProgress')
                : t('dashboard.stat.noRunsInProgress')
            }
          />
          <StatCard
            label={t('dashboard.stat.hypothesesGenerated')}
            value={totals.hypotheses}
            sub={t('dashboard.stat.matchesCount', {count: totals.matches})}
          />
          <StatCard
            label={t('dashboard.stat.currentMode')}
            value={
              systemStatus
                ? systemStatus.provider === 'mock'
                  ? t('dashboard.stat.modeMock')
                  : t('dashboard.stat.modeEngine')
                : '…'
            }
            sub={
              systemStatus
                ? systemStatus.mock_mode
                  ? t('dashboard.stat.noLlmKey')
                  : formatModelName(systemStatus.model_name)
                : undefined
            }
          />
        </section>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <md-outlined-text-field
          type="search"
          label={t('dashboard.search.label')}
          value={query}
          oninput={
            ((e: Event) =>
              setQuery((e.target as HTMLInputElement).value)) as EventListener
          }
          style={{width: '100%', minWidth: '16rem'} as React.CSSProperties}
        />
        <md-chip-set>
          {(
            ['all', 'completed', 'running', 'failed', 'blocked'] as Filter[]
          ).map(f => (
            <md-filter-chip
              key={f}
              selected={filter === f || undefined}
              onclick={(() => setFilter(f)) as EventListener}
            >
              {filterLabel(f, t)}
            </md-filter-chip>
          ))}
        </md-chip-set>
      </div>

      {error && (
        <div
          role="alert"
          className="rounded border p-3 text-sm"
          style={{
            borderColor: 'var(--md-sys-color-error)',
            color: 'var(--md-sys-color-error)',
          }}
        >
          {error}
        </div>
      )}

      {runs === null && !error && <Skeleton />}

      {runs && runs.length === 0 && (
        <div
          className="rounded border p-8 text-center wb-fade-in"
          style={{borderColor: 'var(--md-sys-color-outline-variant)'}}
        >
          <md-icon
            className="mx-auto mb-3 block"
            style={
              {
                color: 'var(--md-sys-color-on-surface-variant)',
                '--md-icon-size': '2rem',
              } as React.CSSProperties
            }
            aria-hidden="true"
          >
            science
          </md-icon>
          <p className="font-medium">{t('dashboard.empty.noRunsYet')}</p>
          <p
            className="text-sm mb-4"
            style={{color: 'var(--md-sys-color-on-surface-variant)'}}
          >
            {t('dashboard.empty.noRunsHint')}
          </p>
          <md-filled-button
            onclick={(() => navigate('/runs/new')) as EventListener}
          >
            {t('dashboard.empty.createFirst')}
          </md-filled-button>
        </div>
      )}

      {filtered && filtered.length === 0 && runs && (
        <div
          className="rounded border p-8 text-center text-sm"
          style={{
            borderColor: 'var(--md-sys-color-outline-variant)',
            color: 'var(--md-sys-color-on-surface-variant)',
          }}
        >
          {t('dashboard.empty.noMatch')}
        </div>
      )}

      {filtered && filtered.length > 0 && (
        <>
          <div className="grid gap-2 sm:hidden wb-fade-in">
            {filtered.map(r => (
              <RunCard
                key={r.id}
                run={r}
                summary={r.is_demo ? demoSummaries[r.id] : summaries[r.id]}
                secondaryLabel={
                  r.is_demo ? t('dashboard.label.matches') : t('label.created')
                }
                secondaryValue={
                  r.is_demo
                    ? (demoSummaries[r.id]?.matches ?? '—')
                    : fmtRelative(r.created_at, t)
                }
                secondaryTitle={r.is_demo ? undefined : fmtDate(r.created_at)}
                isDemo={r.is_demo}
              />
            ))}
          </div>
          <div
            className="hidden sm:block rounded border overflow-hidden wb-fade-in"
            style={{
              borderColor: 'var(--md-sys-color-outline-variant)',
              backgroundColor: 'var(--md-sys-color-surface-container-low)',
            }}
          >
            <table className="w-full text-sm">
              <thead
                style={{
                  backgroundColor: 'var(--md-sys-color-secondary-container)',
                }}
              >
                <tr className="text-left">
                  <th className="px-4 py-2 font-semibold">
                    {t('dashboard.table.researchGoal')}
                  </th>
                  <th className="px-4 py-2 font-semibold w-24 hidden sm:table-cell">
                    {t('label.profile')}
                  </th>
                  <th className="px-4 py-2 font-semibold w-32">
                    {t('label.status')}
                  </th>
                  <th className="px-4 py-2 font-semibold w-24 hidden sm:table-cell">
                    {t('label.provider')}
                  </th>
                  <th className="px-4 py-2 font-semibold w-24 hidden sm:table-cell">
                    {t('label.ideas')}
                  </th>
                  <th
                    className="px-4 py-2 font-semibold w-32"
                    title={t('label.created')}
                  >
                    {t('label.created')}
                  </th>
                </tr>
              </thead>
              <tbody>
                {filtered.map(r => (
                  <tr
                    key={r.id}
                    className="border-t transition-colors hover:bg-[color:var(--md-sys-color-secondary-container)]"
                    style={{borderColor: 'var(--md-sys-color-outline-variant)'}}
                  >
                    <td className="px-4 py-2">
                      <Link
                        to={`/runs/${r.id}`}
                        className="font-medium underline-offset-2 hover:underline"
                      >
                        {r.research_goal}
                      </Link>
                      {r.is_demo && (
                        <span
                          className="ml-2 inline-block rounded px-1.5 py-0.5 text-xs font-medium"
                          style={{
                            backgroundColor:
                              'var(--md-sys-color-secondary-container)',
                            color: 'var(--md-sys-color-on-secondary-container)',
                          }}
                        >
                          {t('label.example')}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2 capitalize hidden sm:table-cell">
                      {r.profile}
                    </td>
                    <td className="px-4 py-2">
                      <RunStatusPill status={r.status} />
                    </td>
                    <td className="px-4 py-2 capitalize hidden sm:table-cell">
                      {r.provider}
                    </td>
                    <td
                      className="px-4 py-2 hidden sm:table-cell"
                      style={{color: 'var(--md-sys-color-on-surface-variant)'}}
                    >
                      {(r.is_demo ? demoSummaries[r.id] : summaries[r.id])
                        ?.hypotheses ?? '—'}
                    </td>
                    <td
                      className="px-4 py-2"
                      style={{color: 'var(--md-sys-color-on-surface-variant)'}}
                      title={r.is_demo ? undefined : fmtDate(r.created_at)}
                    >
                      {r.is_demo
                        ? t('label.example')
                        : fmtRelative(r.created_at, t)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

function RunCard({
  run,
  summary,
  secondaryLabel,
  secondaryValue,
  secondaryTitle,
  isDemo = false,
}: {
  run: Run;
  summary?: RunSummary;
  secondaryLabel: string;
  secondaryValue: number | string;
  secondaryTitle?: string;
  isDemo?: boolean;
}) {
  const t = useT();
  return (
    <Link
      to={`/runs/${run.id}`}
      className="group rounded-xl border p-4 transition-colors active:bg-[color:var(--md-sys-color-secondary-container)]"
      style={{
        borderColor: 'var(--md-sys-color-outline-variant)',
        backgroundColor: 'var(--md-sys-color-surface-container-low)',
      }}
    >
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <RunStatusPill status={run.status} />
          {isDemo && (
            <span
              className="rounded px-1.5 py-0.5 text-xs font-medium"
              style={{
                backgroundColor: 'var(--md-sys-color-secondary-container)',
                color: 'var(--md-sys-color-on-secondary-container)',
              }}
            >
              {t('label.example')}
            </span>
          )}
        </div>
        <md-icon
          className="shrink-0 transition-transform group-active:translate-x-0.5"
          style={{color: 'var(--md-sys-color-primary)', fontSize: '20px'}}
        >
          arrow_forward
        </md-icon>
      </div>
      <h2 className="text-base font-semibold leading-snug">
        {run.research_goal}
      </h2>
      <dl
        className="mt-4 grid grid-cols-3 gap-3 border-t pt-3 text-xs"
        style={{
          borderColor: 'var(--md-sys-color-outline-variant)',
          color: 'var(--md-sys-color-on-surface-variant)',
        }}
      >
        <div>
          <dt className="uppercase tracking-wide">{t('label.profile')}</dt>
          <dd className="mt-1 font-medium capitalize text-[color:var(--md-sys-color-on-surface)]">
            {run.profile}
          </dd>
        </div>
        <div>
          <dt className="uppercase tracking-wide">{t('label.ideas')}</dt>
          <dd className="mt-1 font-medium text-[color:var(--md-sys-color-on-surface)]">
            {summary?.hypotheses ?? '—'}
          </dd>
        </div>
        <div>
          <dt className="uppercase tracking-wide">{secondaryLabel}</dt>
          <dd
            className="mt-1 font-medium text-[color:var(--md-sys-color-on-surface)]"
            title={secondaryTitle}
          >
            {secondaryValue}
          </dd>
        </div>
      </dl>
    </Link>
  );
}

function StatCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: number | string;
  sub?: string;
}) {
  return (
    <div
      className="rounded border p-3"
      style={{
        borderColor: 'var(--md-sys-color-outline-variant)',
        backgroundColor: 'var(--md-sys-color-surface-container-low)',
      }}
    >
      <div
        className="text-xs uppercase tracking-wide"
        style={{color: 'var(--md-sys-color-on-surface-variant)'}}
      >
        {label}
      </div>
      <div className="text-2xl font-semibold mt-1">{value}</div>
      {sub && (
        <div
          className="text-xs mt-0.5"
          style={{color: 'var(--md-sys-color-on-surface-variant)'}}
        >
          {sub}
        </div>
      )}
    </div>
  );
}

function Skeleton() {
  return (
    <div className="space-y-2" aria-busy="true">
      {['sk-a', 'sk-b', 'sk-c', 'sk-d'].map(k => (
        <div key={k} className="wb-skeleton h-10" />
      ))}
    </div>
  );
}
