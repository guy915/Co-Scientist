import {
  type RefObject,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type CSSProperties,
  useLayoutEffect,
} from 'react';
import {Icon, type IconName} from '@/components/icon';
import {
  type ByokProvider,
  getStoredApiKey,
  getStoredApiProvider,
  setStoredApiKey,
  setStoredApiProvider,
  type ModelTier,
  getStoredModel,
  setStoredModel,
  BYOK_PROVIDERS,
} from '@/lib/client_id';
import {
  useBackgroundInert,
  useEscapeKey,
  useFocusTrap,
  useRestoreFocusOnClose,
} from '../hooks/dom';
import {type Mode, useTheme} from '../theme_context';
import {
  type ByokModelCatalog,
  type FreeUsage,
  fetchByokModelCatalog,
  fetchFreeUsage,
} from '@/api/system';

// Moves focus to `ref`'s element once on mount, so keyboard/screen-reader
// users land inside a newly opened dialog rather than on whatever was
// focused behind it.
function useFocusOnMount(ref: RefObject<HTMLElement | null>) {
  useEffect(() => {
    ref.current?.focus();
  }, [ref]);
}

// Model section's BYOK fields: a local editable copy of the persisted key
// (written back to storage only on blur/Enter, not every keystroke) plus
// the provider choice (persisted on change, since a select commits whole
// values). Saving is silent: the field showing the value it now holds is
// the confirmation, so a toast only covered the page to repeat it.
function useApiKeyField() {
  // Local editable copy of the persisted key; only written back to storage on
  // blur/Enter (see onSave), not on every keystroke.
  const [apiKey, setApiKey] = useState(getStoredApiKey);
  const [provider, setProvider] = useState<ByokProvider>(getStoredApiProvider);

  // Persists the API key (trimmed; a blank value clears it, see
  // setStoredApiKey) only when it actually changed, then re-syncs local
  // state from storage.
  function onSave() {
    if (apiKey.trim() === getStoredApiKey()) return;
    setStoredApiKey(apiKey);
    setApiKey(getStoredApiKey());
  }

  // Persists the provider choice immediately (a select commits whole
  // values, unlike the free-text key field).
  function onProviderChange(next: ByokProvider) {
    if (next === getStoredApiProvider()) return;
    setStoredApiProvider(next);
    setProvider(getStoredApiProvider());
  }

  return {
    apiKey,
    onApiKeyChange: setApiKey,
    provider,
    onProviderChange,
    onSave,
  };
}

// Dialog header: title plus the close button that also anchors the
// open-focus behavior (see useFocusOnMount).
function SettingsDialogHeader({
  onClose,
  closeRef,
}: {
  onClose: () => void;
  closeRef: RefObject<HTMLButtonElement | null>;
}) {
  return (
    <header className="ucs-settings-dialog-header">
      <h2 className="ucs-settings-dialog-title">Settings</h2>
      <button
        ref={closeRef}
        type="button"
        className="ucs-settings-dialog-close"
        aria-label="Close settings"
        onClick={onClose}
      >
        <Icon aria-hidden="true" name="close" />
      </button>
    </header>
  );
}

/**
 * Centered Settings dialog with a section rail (Appearance, Model),
 * matching the reference product's settings window.
 *
 * @param props The active section and the change/close callbacks.
 */
interface SettingsDialogProps {
  section: SettingsSection;
  onSectionChange: (section: SettingsSection) => void;
  onClose: () => void;
}

export function SettingsDialog({
  section,
  onSectionChange,
  onClose,
}: SettingsDialogProps) {
  const theme = useTheme();
  const closeRef = useRef<HTMLButtonElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const apiKeyField = useApiKeyField();

  // Declared before useFocusOnMount so its capture effect runs first and
  // sees the real opener rather than the close button useFocusOnMount is
  // about to focus (see useRestoreFocusOnClose's own doc comment).
  useRestoreFocusOnClose();
  // Keyboard/screen-reader users can't reach the page behind the dialog
  // (Tab is trapped) or perceive it (it's marked inert) while this is open.
  useFocusTrap(rootRef);
  useBackgroundInert(rootRef);
  useFocusOnMount(closeRef);
  useEscapeKey(onClose, true);

  return (
    <div className="ucs-settings-dialog-root" ref={rootRef}>
      <div
        className="ucs-settings-dialog-scrim"
        aria-hidden="true"
        onClick={onClose}
      />
      <div
        className="ucs-settings-dialog"
        role="dialog"
        aria-modal="true"
        aria-label="Settings"
      >
        <SettingsDialogHeader onClose={onClose} closeRef={closeRef} />
        <div className="ucs-settings-dialog-body">
          <SettingsNav section={section} onSectionChange={onSectionChange} />
          <div className="ucs-settings-dialog-panel">
            {section === 'appearance' && (
              <AppearanceSection mode={theme.mode} setMode={theme.setMode} />
            )}
            {section === 'model' && <ModelSection {...apiKeyField} />}
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * The dialog's section rail options; also the type of the currently-open
 * section, controlled by the parent (see the `section`/`onSectionChange`
 * props on SettingsDialog in settings_dialog.tsx).
 */
export type SettingsSection = 'appearance' | 'model';

// Options rendered in the Appearance section's theme segmented control.
// Selecting one calls useTheme()'s setMode, which persists the choice (see
// theme_context.tsx) and updates the resolved MD3 theme immediately.
const THEME_MODES: {mode: Mode; icon: IconName; label: string}[] = [
  {mode: 'system', icon: 'computer', label: 'System'},
  {mode: 'light', icon: 'light_mode', label: 'Light'},
  {mode: 'dark', icon: 'dark_mode', label: 'Dark'},
];

// Section-rail entries, in display order. Also consumed by the nav rail's
// Settings popover menu (layout_nav_rail.tsx), so the two surfaces can't
// drift apart.
export const SETTINGS_SECTIONS: {
  section: SettingsSection;
  icon: IconName;
  label: string;
}[] = [
  {section: 'appearance', icon: 'palette', label: 'Appearance'},
  {section: 'model', icon: 'neurology', label: 'Model'},
];

// Appearance section: theme mode segmented control (system/light/dark).
export function AppearanceSection({
  mode,
  setMode,
}: {
  mode: Mode;
  setMode: (mode: Mode) => void;
}) {
  return (
    <section className="ucs-settings-card">
      <h3 className="ucs-settings-card-title">Theme</h3>
      <div
        className="ucs-theme-segment ucs-theme-segment--dialog"
        role="group"
        aria-label="Theme"
      >
        {THEME_MODES.map(option => (
          <button
            key={option.mode}
            type="button"
            className={
              mode === option.mode
                ? 'ucs-theme-button ucs-theme-button--dialog selected'
                : 'ucs-theme-button ucs-theme-button--dialog'
            }
            aria-pressed={mode === option.mode}
            onClick={() => setMode(option.mode)}
          >
            <Icon
              aria-hidden="true"
              className="ucs-theme-button-icon"
              name={option.icon}
            />
            <span>{option.label}</span>
          </button>
        ))}
      </div>
    </section>
  );
}

// Hint under the key field: where to get a key from whichever provider is
// selected. Every provider issues keys from its own console, so the link
// follows the choice rather than standing for one of them.
function ApiKeyHint({provider}: {provider: ByokProvider}) {
  const {url, article} = PROVIDER_KEY_PAGES[provider];
  return (
    <p className="ucs-settings-field-hint">
      <a
        className="ucs-settings-field-link"
        href={url}
        target="_blank"
        rel="noreferrer"
      >
        Get {article} {PROVIDER_LABELS[provider]} API key
        <Icon aria-hidden="true" name="open_in_new" />
      </a>
    </p>
  );
}

// Model section: bring-your-own-key provider choice and key entry, then the
// supervisor and worker model selects side by side. The key saves on blur or
// Enter; the provider and models persist on change.
export function ModelSection({
  apiKey,
  onApiKeyChange,
  provider,
  onProviderChange,
  onSave,
}: {
  apiKey: string;
  onApiKeyChange: (value: string) => void;
  provider: ByokProvider;
  onProviderChange: (value: ByokProvider) => void;
  onSave: () => void;
}) {
  const modelFields = useModelFields(provider);
  return (
    <section className="ucs-settings-card">
      <h3 className="ucs-settings-card-title">Model</h3>
      <ProviderSelectLabel />
      <ProviderSelect provider={provider} onChange={onProviderChange} />
      <label
        className="ucs-settings-field-label ucs-settings-field-label--spaced"
        htmlFor="cosci-settings-api-key"
      >
        {PROVIDER_LABELS[provider]} API key
      </label>
      <input
        id="cosci-settings-api-key"
        className="ucs-settings-field-input"
        type="password"
        autoComplete="off"
        placeholder={`Paste your ${PROVIDER_LABELS[provider]} API key`}
        value={apiKey}
        onChange={event => onApiKeyChange(event.target.value)}
        onBlur={onSave}
        onKeyDown={event => {
          if (event.key === 'Enter') onSave();
        }}
      />
      <ApiKeyHint provider={provider} />
      <ModelSelectors hasKey={apiKey.trim() !== ''} fields={modelFields} />
    </section>
  );
}

// Section rail: list of nav buttons for switching between the dialog's
// sections (see SETTINGS_SECTIONS above), highlighting whichever is
// currently active.
export function SettingsNav({
  section,
  onSectionChange,
}: {
  section: SettingsSection;
  onSectionChange: (section: SettingsSection) => void;
}) {
  return (
    <nav className="ucs-settings-dialog-nav" aria-label="Settings sections">
      {SETTINGS_SECTIONS.map(item => {
        const active = item.section === section;
        return (
          <button
            key={item.section}
            type="button"
            className={
              active
                ? 'ucs-settings-nav-item ucs-settings-nav-item--active'
                : 'ucs-settings-nav-item'
            }
            aria-current={active ? 'true' : undefined}
            onClick={() => onSectionChange(item.section)}
          >
            <Icon
              aria-hidden="true"
              className="ucs-settings-nav-icon"
              name={item.icon}
            />
            <span>{item.label}</span>
          </button>
        );
      })}
    </nav>
  );
}

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

// Both model tiers use the same menu as the provider chooser; the worker
// menu opens leftward so it stays over the dialog.
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
  const triggerId = `cosci-settings-${tier}-model`;
  const labelId = `${triggerId}-label`;
  return (
    <div className="ucs-settings-model-field">
      <label
        id={labelId}
        className="ucs-settings-field-label"
        htmlFor={triggerId}
      >
        {TIER_LABELS[tier]}
      </label>
      <SettingsSelect
        value={value}
        options={options}
        optionLabel={modelLabel}
        name={TIER_LABELS[tier]}
        triggerId={triggerId}
        labelId={labelId}
        disabled={disabled}
        align={tier === 'worker' ? 'end' : 'start'}
        onChange={onChange}
      />
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

// Closes a chooser on outside pointerdown, with a listener only while open.
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
      const box = trigger.getBoundingClientRect();
      el.style.minWidth = `${box.width}px`;
      const origin = el.getBoundingClientRect();
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

// Shared provider/model chooser. Real menu buttons preserve Tab and Enter
// behavior; selecting the current value only dismisses the menu.
function SettingsSelect<T extends string>({
  value,
  options,
  optionLabel,
  name,
  triggerId,
  labelId,
  disabled = false,
  align = 'start',
  onChange,
}: {
  value: T;
  options: readonly T[];
  optionLabel: (option: T) => string;
  name: string;
  triggerId: string;
  labelId: string;
  disabled?: boolean;
  align?: 'start' | 'end';
  onChange: (option: T) => void;
}) {
  const [open, setOpen] = useState(false);
  const container = useRef<HTMLDivElement>(null);
  useCloseOnOutsidePointer(open, container, () => setOpen(false));
  const {menuRef, menuStyle} = useAnchoredMenu(open, container, align);

  // Escape dismisses the menu before the dialog's window listener sees it.
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
        id={triggerId}
        className="ucs-provider-trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-labelledby={`${labelId} ${triggerId}`}
        disabled={disabled}
        onClick={() => setOpen(current => !current)}
      >
        <span>{optionLabel(value)}</span>
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
          aria-label={name}
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
              <span>{optionLabel(option)}</span>
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
  );
}

/** Provider chooser for the Settings dialog's Model section. */
export function ProviderSelect({
  provider,
  onChange,
}: {
  provider: ByokProvider;
  onChange: (provider: ByokProvider) => void;
}) {
  return (
    <SettingsSelect
      value={provider}
      options={BYOK_PROVIDERS}
      optionLabel={option => PROVIDER_LABELS[option]}
      name="Provider"
      triggerId={TRIGGER_ID}
      labelId={LABEL_ID}
      onChange={onChange}
    />
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
