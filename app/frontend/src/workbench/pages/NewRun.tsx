import '@material/web/textfield/outlined-text-field.js';
import '@material/web/button/filled-button.js';
import '@material/web/button/text-button.js';

import {type FormEvent, useState} from 'react';
import {useNavigate} from 'react-router-dom';
import {createRun, type RunProfile, startRun} from '@/api/runs';
import {useLocale, useT} from '@/i18n';

const SUGGESTED_KEYS = [
  'newRun.suggested.1',
  'newRun.suggested.2',
  'newRun.suggested.3',
] as const;

/**
 * Renders the form for configuring and starting a new research run.
 */
export function NewRun() {
  const t = useT();
  const {locale} = useLocale();
  const navigate = useNavigate();
  const [goal, setGoal] = useState('');
  const [profile, setProfile] = useState<RunProfile>('standard');
  const [advanced, setAdvanced] = useState(false);
  const [initialCount, setInitialCount] = useState<number | ''>('');
  const [maxIters, setMaxIters] = useState<number | ''>('');
  const [evolutionCount, setEvolutionCount] = useState<number | ''>('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    if (!goal.trim()) {
      setError(t('newRun.goal.required'));
      return;
    }
    setSubmitting(true);
    try {
      const run = await createRun({
        research_goal: goal.trim(),
        profile,
        language: locale,
        initial_hypotheses_count:
          typeof initialCount === 'number' ? initialCount : undefined,
        max_iterations: typeof maxIters === 'number' ? maxIters : undefined,
        evolution_max_count:
          typeof evolutionCount === 'number' ? evolutionCount : undefined,
      });
      await startRun(run.id);
      void navigate(`/runs/${run.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSubmitting(false);
    }
  }

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <header>
        <h1 className="md-typescale-headline-medium text-2xl font-semibold tracking-tight">
          {t('newRun.title')}
        </h1>
        <p
          className="text-sm"
          style={{color: 'var(--md-sys-color-on-surface-variant)'}}
        >
          {t('newRun.subtitle')}
        </p>
      </header>

      <form
        onSubmit={onSubmit}
        className="space-y-5 rounded border p-4 sm:p-5"
        style={{
          borderColor: 'var(--md-sys-color-outline-variant)',
          backgroundColor: 'var(--md-sys-color-surface-container-low)',
        }}
      >
        <div className="space-y-1.5">
          <md-outlined-text-field
            type="textarea"
            label={t('newRun.goal.label')}
            rows={4}
            value={goal}
            oninput={
              ((e: Event) =>
                setGoal((e.target as HTMLInputElement).value)) as EventListener
            }
            placeholder={t('newRun.goal.placeholder')}
            style={{width: '100%'} as React.CSSProperties}
          />
          <div
            className="text-xs flex flex-col gap-1.5 mt-2 px-1"
            style={{color: 'var(--md-sys-color-on-surface-variant)'}}
          >
            <span className="font-medium">{t('newRun.suggested.heading')}</span>
            <div className="flex flex-col gap-2 items-start mt-0.5">
              {SUGGESTED_KEYS.map(key => {
                const s = t(key);
                return (
                  <button
                    key={key}
                    type="button"
                    onClick={() => setGoal(s)}
                    className="text-left cursor-pointer hover:underline text-xs flex items-start gap-1.5"
                    style={{
                      color: 'var(--md-sys-color-primary)',
                      lineHeight: '1.4',
                    }}
                  >
                    <span className="opacity-70 font-mono">•</span>
                    <span>{s}</span>
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">
            {t('newRun.profile.legend')}
          </legend>
          <div className="grid grid-cols-2 gap-3">
            <label
              className="flex items-start gap-2 rounded border p-3 cursor-pointer"
              style={{
                borderColor:
                  profile === 'standard'
                    ? 'var(--md-sys-color-primary)'
                    : 'var(--md-sys-color-outline-variant)',
              }}
            >
              <input
                type="radio"
                name="profile"
                value="standard"
                checked={profile === 'standard'}
                onChange={() => setProfile('standard')}
              />
              <span>
                <div className="font-medium">{t('label.standard')}</div>
                <div
                  className="text-xs"
                  style={{color: 'var(--md-sys-color-on-surface-variant)'}}
                >
                  {t('newRun.profile.standard.desc')}
                </div>
              </span>
            </label>
            <label
              className="flex items-start gap-2 rounded border p-3 cursor-pointer"
              style={{
                borderColor:
                  profile === 'advanced'
                    ? 'var(--md-sys-color-primary)'
                    : 'var(--md-sys-color-outline-variant)',
              }}
            >
              <input
                type="radio"
                name="profile"
                value="advanced"
                checked={profile === 'advanced'}
                onChange={() => setProfile('advanced')}
              />
              <span>
                <div className="font-medium">{t('label.advanced')}</div>
                <div
                  className="text-xs"
                  style={{color: 'var(--md-sys-color-on-surface-variant)'}}
                >
                  {t('newRun.profile.advanced.desc')}
                </div>
              </span>
            </label>
          </div>
        </fieldset>

        <details
          className="rounded border"
          style={{borderColor: 'var(--md-sys-color-outline-variant)'}}
          open={advanced}
          onToggle={e => setAdvanced((e.target as HTMLDetailsElement).open)}
        >
          <summary className="px-3 py-2 cursor-pointer text-sm font-medium">
            {t('newRun.overrides.summary')}
          </summary>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 p-3 pt-0">
            <NumberField
              label={t('newRun.overrides.initial')}
              value={initialCount}
              onChange={setInitialCount}
            />
            <NumberField
              label={t('newRun.overrides.maxIters')}
              value={maxIters}
              onChange={setMaxIters}
            />
            <NumberField
              label={t('newRun.overrides.evolution')}
              value={evolutionCount}
              onChange={setEvolutionCount}
            />
          </div>
        </details>

        {error && (
          <div
            role="alert"
            className="text-sm rounded border p-2"
            style={{
              borderColor: 'var(--md-sys-color-error)',
              color: 'var(--md-sys-color-error)',
            }}
          >
            {error}
          </div>
        )}

        <div className="flex justify-end">
          <md-filled-button type="submit" disabled={submitting || undefined}>
            {submitting ? t('action.starting') : t('action.startRun')}
          </md-filled-button>
        </div>
      </form>
    </div>
  );
}

function NumberField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number | '';
  onChange: (v: number | '') => void;
}) {
  return (
    <md-outlined-text-field
      type="number"
      label={label}
      value={value === '' ? '' : String(value)}
      min="1"
      max="20"
      oninput={
        ((e: Event) => {
          const v = (e.target as HTMLInputElement).value;
          onChange(v === '' ? '' : Number(v));
        }) as EventListener
      }
      style={{width: '100%'} as React.CSSProperties}
    />
  );
}
