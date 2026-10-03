import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type CSSProperties,
  useLayoutEffect,
} from 'react';
import {
  type ByokModelCatalog,
  type FreeUsage,
  fetchByokModelCatalog,
  fetchFreeUsage,
} from '@/api/system';
import {Icon} from '@/components/icon';
import {
  type ByokProvider,
  type ModelTier,
  getStoredModel,
  setStoredModel,
  BYOK_PROVIDERS,
} from '@/lib/api_key';

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
// (settings_model_select.tsx), for the same reasons, with the options
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
  // The right-hand (worker) select opens leftward, back over the dialog.
  const {menuRef, menuStyle} = useAnchoredMenu(
    open,
    container,
    tier === 'worker' ? 'end' : 'start',
  );
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
          <span>{modelLabel(value)}</span>
          <Icon
            aria-hidden="true"
            className="ucs-provider-chevron"
            name="expand_more"
          />
        </button>
        {open && !disabled && (
          <div
            ref={menuRef}
            style={menuStyle}
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
      {count} Add a key to use the chosen models and other run types.
    </p>
  );
}

/**
 * The Supervisor and Worker model selects, side by side, under the key.
 * Choosable without a key: the choice is stored and rides along once a key
 * is added (byokHeaders sends models only with a key). Disabled only until
 * the catalog loads.
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
  const disabled = fields.options.length === 0;
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

/** Display names for the BYOK provider choices. */
export const PROVIDER_LABELS: Record<ByokProvider, string> = {
  anthropic: 'Anthropic',
  deepseek: 'DeepSeek',
  gemini: 'Gemini',
  openai: 'OpenAI',
  openrouter: 'OpenRouter',
};

/**
 * Where each provider issues API keys, and the article its name takes in the
 * hint under the key field.
 *
 * The article is stored rather than derived: a leading-vowel test is right
 * for these five names and wrong for the next one that starts with a
 * consonant sound. The name itself is not stored -- it comes from
 * PROVIDER_LABELS above, so renaming a provider cannot leave the link
 * calling it something else.
 */
export const PROVIDER_KEY_PAGES: Record<
  ByokProvider,
  {url: string; article: 'a' | 'an'}
> = {
  anthropic: {
    url: 'https://platform.claude.com/settings/keys',
    article: 'an',
  },
  deepseek: {url: 'https://platform.deepseek.com/api_keys', article: 'a'},
  gemini: {url: 'https://aistudio.google.com/apikey', article: 'a'},
  openai: {url: 'https://platform.openai.com/api-keys', article: 'an'},
  openrouter: {url: 'https://openrouter.ai/settings/keys', article: 'an'},
};

const TRIGGER_ID = 'cosci-settings-provider';
const LABEL_ID = 'cosci-settings-provider-label';

// Closes the menu on a pointerdown outside `container` (also used by the
// model selects, settings_model_select.tsx). Registered only
// while open, matching the shell's own popover dismissal
// (layout_hooks.useDismissPanelOnOutsideClick).
export function useCloseOnOutsidePointer(
  open: boolean,
  container: React.RefObject<HTMLDivElement | null>,
  onClose: () => void,
) {
  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: PointerEvent) {
      if (!container.current?.contains(event.target as Node)) onClose();
    }
    document.addEventListener('pointerdown', onPointerDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
    };
  }, [open, container, onClose]);
}

// Gap between a trigger and the menu it opens.
const MENU_GAP_PX = 6;

/**
 * Places an open menu under its trigger with `position: fixed`, so the
 * Settings panel's scroll box (`overflow-y: auto`) cannot clip it and the
 * menu may overflow the panel and the dialog edges.
 *
 * A fixed box's containing block is the viewport unless an ancestor has a
 * transform, and the centered dialog has one. So the hook does not assume
 * either: it first places the menu at 0,0, reads where that lands, and
 * subtracts that origin. Re-placed on any scroll or resize while open.
 *
 * @param open Whether the menu is rendered.
 * @param anchor The wrapper holding the trigger; its box sets the position.
 * @param align `start` opens rightward from the trigger's left edge, `end`
 *   leftward from its right edge.
 * @returns The menu's ref and its inline style.
 */
export function useAnchoredMenu(
  open: boolean,
  anchor: React.RefObject<HTMLDivElement | null>,
  align: 'start' | 'end' = 'start',
) {
  const menu = useRef<HTMLDivElement>(null);
  const [style, setStyle] = useState<CSSProperties>({});
  useLayoutEffect(() => {
    if (!open) return;
    function place() {
      const el = menu.current;
      const trigger = anchor.current;
      if (!el || !trigger) return;
      el.style.top = '0px';
      el.style.left = '0px';
      const origin = el.getBoundingClientRect();
      const box = trigger.getBoundingClientRect();
      const left = align === 'end' ? box.right - origin.width : box.left;
      const next = {
        top: box.bottom + MENU_GAP_PX - origin.top,
        left: left - origin.left,
        minWidth: box.width,
      };
      el.style.top = `${next.top}px`;
      el.style.left = `${next.left}px`;
      setStyle(next);
    }
    place();
    window.addEventListener('scroll', place, true);
    window.addEventListener('resize', place);
    return () => {
      window.removeEventListener('scroll', place, true);
      window.removeEventListener('resize', place);
    };
  }, [open, anchor, align]);
  return {menuRef: menu, menuStyle: style};
}

// One row of the open menu: a real button (so Tab and Enter work without an
// activedescendant dance), carrying a check on the current choice so the
// selection reads without relying on the highlight alone.
function ProviderOption({
  option,
  selected,
  onSelect,
}: {
  option: ByokProvider;
  selected: boolean;
  onSelect: (option: ByokProvider) => void;
}) {
  return (
    <button
      type="button"
      role="menuitemradio"
      aria-checked={selected}
      className="ucs-provider-option"
      onClick={() => onSelect(option)}
    >
      <span>{PROVIDER_LABELS[option]}</span>
      {selected && (
        <Icon
          aria-hidden="true"
          className="ucs-provider-option-check"
          name="check"
        />
      )}
    </button>
  );
}

/**
 * Provider chooser for the Settings dialog's Model section.
 *
 * A button plus an own-markup menu rather than a native `<select>`: the
 * native control's list is drawn by the browser in its own style rather than
 * by the workspace, and cannot carry the check mark or the row treatment the
 * rest of the dialog's menus use.
 *
 * @param provider The currently chosen provider.
 * @param onChange Called with the newly chosen provider (never with the one
 *   already selected -- picking the current value just closes the menu).
 */
export function ProviderSelect({
  provider,
  onChange,
}: {
  provider: ByokProvider;
  onChange: (provider: ByokProvider) => void;
}) {
  const [open, setOpen] = useState(false);
  const container = useRef<HTMLDivElement>(null);
  useCloseOnOutsidePointer(open, container, () => setOpen(false));
  const {menuRef, menuStyle} = useAnchoredMenu(open, container);

  function onSelect(option: ByokProvider) {
    setOpen(false);
    if (option !== provider) onChange(option);
  }

  // Escape closes the menu and stops there: the Settings dialog listens for
  // Escape on the window to close itself, and dismissing both at once would
  // throw the reader out of Settings for cancelling a dropdown.
  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Escape' && open) {
      event.stopPropagation();
      setOpen(false);
    }
  }

  return (
    <div className="ucs-provider-select" ref={container} onKeyDown={onKeyDown}>
      <button
        type="button"
        id={TRIGGER_ID}
        className="ucs-provider-trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-labelledby={`${LABEL_ID} ${TRIGGER_ID}`}
        onClick={() => setOpen(current => !current)}
      >
        <span>{PROVIDER_LABELS[provider]}</span>
        <Icon
          aria-hidden="true"
          className="ucs-provider-chevron"
          name="expand_more"
        />
      </button>
      {open && (
        <div
          ref={menuRef}
          style={menuStyle}
          className="ucs-provider-menu"
          role="menu"
          aria-label="Provider"
        >
          {BYOK_PROVIDERS.map(option => (
            <ProviderOption
              key={option}
              option={option}
              selected={option === provider}
              onSelect={onSelect}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/** The `<label>` that names the trigger; rendered by the Model section. */
export function ProviderSelectLabel() {
  return (
    <label
      id={LABEL_ID}
      className="ucs-settings-field-label"
      htmlFor={TRIGGER_ID}
    >
      Provider
    </label>
  );
}
