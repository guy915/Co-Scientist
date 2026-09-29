import {useEffect, useRef, useState, type KeyboardEvent} from 'react';
import {
  type ByokModelCatalog,
  type FreeUsage,
  fetchByokModelCatalog,
  fetchFreeUsage,
} from '@/api/models';
import {Icon} from '@/components/icon';
import {
  type ByokProvider,
  type ModelTier,
  getStoredModel,
  setStoredModel,
} from '@/lib/api_key';
import {useCloseOnOutsidePointer} from './settings_provider_select';

/** Shown in a disabled select while no API key is set. */
export const FREE_MODEL_LABEL = 'Free model';

const TIER_LABELS: Record<ModelTier, string> = {
  supervisor: 'Supervisor model',
  worker: 'Worker model',
};

/**
 * Display name for a litellm model id: the provider prefix is dropped, since
 * the Provider select above already names it.
 *
 * @param model A litellm model id, e.g. `deepseek/deepseek-v4-flash`.
 * @returns The id without its first path segment.
 */
export function modelLabel(model: string): string {
  const slash = model.indexOf('/');
  return slash < 0 ? model : model.slice(slash + 1);
}

// One tier's chooser: the same button-plus-menu shape as ProviderSelect
// (settings_provider_select.tsx), for the same reasons, with the options
// supplied by the caller.
function ModelSelect({
  tier,
  value,
  options,
  disabled,
  onChange,
}: {
  tier: ModelTier;
  value: string;
  options: string[];
  disabled: boolean;
  onChange: (model: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const container = useRef<HTMLDivElement>(null);
  useCloseOnOutsidePointer(open, container, () => setOpen(false));
  const triggerId = `cosci-settings-${tier}-model`;
  const labelId = `${triggerId}-label`;

  // Escape closes only the menu, not the dialog (see ProviderSelect).
  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Escape' && open) {
      event.stopPropagation();
      setOpen(false);
    }
  }

  return (
    <div className="ucs-settings-model-field">
      <label
        id={labelId}
        className="ucs-settings-field-label"
        htmlFor={triggerId}
      >
        {TIER_LABELS[tier]}
      </label>
      <div
        className="ucs-provider-select"
        ref={container}
        onKeyDown={onKeyDown}
      >
        <button
          type="button"
          id={triggerId}
          className="ucs-provider-trigger"
          aria-haspopup="menu"
          aria-expanded={open}
          aria-labelledby={`${labelId} ${triggerId}`}
          disabled={disabled}
          onClick={() => setOpen(current => !current)}
        >
          <span>{disabled ? FREE_MODEL_LABEL : modelLabel(value)}</span>
          <Icon
            aria-hidden="true"
            className="ucs-provider-chevron"
            name="expand_more"
          />
        </button>
        {open && !disabled && (
          <div
            className="ucs-provider-menu"
            role="menu"
            aria-label={TIER_LABELS[tier]}
          >
            {options.map(option => (
              <button
                key={option}
                type="button"
                role="menuitemradio"
                aria-checked={option === value}
                className="ucs-provider-option"
                onClick={() => {
                  setOpen(false);
                  if (option !== value) onChange(option);
                }}
              >
                <span>{modelLabel(option)}</span>
                {option === value && (
                  <Icon
                    aria-hidden="true"
                    className="ucs-provider-option-check"
                    name="check"
                  />
                )}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// Fetches the provider model catalog and the caller's free usage once per
// mount. Either may stay null: the selects then stay disabled and the free
// usage note stays silent, rather than guessing.
function useModelSettingsData() {
  const [catalog, setCatalog] = useState<ByokModelCatalog | null>(null);
  const [freeUsage, setFreeUsage] = useState<FreeUsage | null>(null);
  useEffect(() => {
    let live = true;
    fetchByokModelCatalog()
      .then(next => live && setCatalog(next))
      .catch(() => undefined);
    fetchFreeUsage()
      .then(next => live && setFreeUsage(next))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);
  return {catalog, freeUsage};
}

// The provider's offered models, default first; empty until the catalog
// loads (or when it failed to).
function providerOptions(
  catalog: ByokModelCatalog | null,
  provider: ByokProvider,
): string[] {
  return catalog?.[provider] ?? [];
}

// Both tiers' stored choices; blank means the provider's default.
function storedChoices(): Record<ModelTier, string> {
  return {
    worker: getStoredModel('worker'),
    supervisor: getStoredModel('supervisor'),
  };
}

/**
 * State for the Model section's two model selects: the provider catalog
 * (fetched once), each tier's stored choice, and the caller's free usage.
 *
 * @param provider The chosen BYOK provider; a change resets both choices to
 *   the new provider's defaults (setStoredApiProvider clears storage).
 */
export function useModelFields(provider: ByokProvider) {
  const {catalog, freeUsage} = useModelSettingsData();
  const [choices, setChoices] = useState(storedChoices);
  useEffect(() => setChoices(storedChoices()), [provider]);
  const options = providerOptions(catalog, provider);
  // A blank choice means the provider default: the catalog's first entry.
  const fallback = options[0] ?? '';

  function onModelChange(tier: ModelTier, model: string) {
    setStoredModel(tier, model);
    setChoices(current => ({...current, [tier]: model}));
  }

  return {
    options,
    worker: choices.worker || fallback,
    supervisor: choices.supervisor || fallback,
    freeUsage,
    onModelChange,
  };
}

/** The Model section's model-select state (see useModelFields). */
export type ModelFields = ReturnType<typeof useModelFields>;

// What a keyless user gets: free usage, limited to express runs and a daily
// run count. Silent until the count is known, and on an offline deployment,
// where keyless runs spend nothing and nothing is limited.
function FreeUsageNote({usage}: {usage: FreeUsage | null}) {
  if (!usage?.enforced) return null;
  const count =
    usage.limit === null
      ? ''
      : ` ${usage.remaining} of ${usage.limit} free runs left today.`;
  return (
    <p className="ucs-settings-field-hint" role="status">
      No API key: you are on free usage. Only Express runs are available.
      {count} Add a key to choose models and run types.
    </p>
  );
}

/**
 * The Supervisor and Worker model selects, side by side, under the key.
 * Disabled (showing the free model) until an API key is set.
 *
 * @param hasKey Whether an API key is stored.
 * @param fields The state from useModelFields.
 */
export function ModelSelectors({
  hasKey,
  fields,
}: {
  hasKey: boolean;
  fields: ModelFields;
}) {
  const disabled = !hasKey || fields.options.length === 0;
  return (
    <>
      <div className="ucs-settings-model-grid">
        {(['supervisor', 'worker'] as const).map(tier => (
          <ModelSelect
            key={tier}
            tier={tier}
            value={fields[tier]}
            options={fields.options}
            disabled={disabled}
            onChange={model => fields.onModelChange(tier, model)}
          />
        ))}
      </div>
      {!hasKey && <FreeUsageNote usage={fields.freeUsage} />}
    </>
  );
}
