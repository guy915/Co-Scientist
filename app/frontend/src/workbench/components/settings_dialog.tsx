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
  type ModelChoice,
  type ModelTier,
  BYOK_PROVIDERS,
  fallbackProvider,
  getStoredApiKey,
  getStoredApiProvider,
  getStoredModel,
  keyedProviders,
  setStoredApiKey,
  setStoredApiProvider,
  setStoredModel,
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

// Focus newly opened dialogs internally so keyboard and assistive-technology
// users do not remain behind them.
function useFocusOnMount(ref: RefObject<HTMLElement | null>) {
  useEffect(() => {
    ref.current?.focus();
  }, [ref]);
}

// Free-text credentials commit on blur/Enter; selections commit whole values
// immediately. Saving silently avoids covering the page with redundant
// confirmation. The field edits the key of the provider being viewed.
function useApiKeyField() {
  const [provider, setProvider] = useState<ByokProvider>(getStoredApiProvider);
  const [apiKey, setApiKey] = useState(() => getStoredApiKey(provider));
  const [savedProviders, setSavedProviders] = useState(keyedProviders);

  function onSave() {
    if (apiKey.trim() === getStoredApiKey(provider)) return;
    setStoredApiKey(apiKey, provider);
    setApiKey(getStoredApiKey(provider));
    setSavedProviders(keyedProviders());
  }

  function onProviderChange(next: ByokProvider) {
    if (next === provider) return;
    setStoredApiProvider(next);
    setProvider(next);
    setApiKey(getStoredApiKey(next));
  }

  return {
    apiKey,
    onApiKeyChange: setApiKey,
    provider,
    onProviderChange,
    onSave,
    savedProviders,
  };
}

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

  // Capture the opener before the focus-on-open effect moves focus into the
  // dialog.
  useRestoreFocusOnClose();
  // Background content must be inert as well as outside the Tab trap, including
  // for assistive technology.
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

export type SettingsSection = 'appearance' | 'model';

const THEME_MODES: {mode: Mode; icon: IconName; label: string}[] = [
  {mode: 'system', icon: 'computer', label: 'System'},
  {mode: 'light', icon: 'light_mode', label: 'Light'},
  {mode: 'dark', icon: 'dark_mode', label: 'Dark'},
];

export const SETTINGS_SECTIONS: {
  section: SettingsSection;
  icon: IconName;
  label: string;
}[] = [
  {section: 'appearance', icon: 'palette', label: 'Appearance'},
  {section: 'model', icon: 'neurology', label: 'Model'},
];

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

export function ModelSection({
  apiKey,
  onApiKeyChange,
  provider,
  onProviderChange,
  onSave,
  savedProviders,
}: {
  apiKey: string;
  onApiKeyChange: (value: string) => void;
  provider: ByokProvider;
  onProviderChange: (value: ByokProvider) => void;
  onSave: () => void;
  savedProviders: ByokProvider[];
}) {
  const modelFields = useModelFields(provider, savedProviders);
  return (
    <section className="ucs-settings-card">
      <h3 className="ucs-settings-card-title">Model</h3>
      <ProviderSelectLabel />
      <ProviderSelect
        provider={provider}
        savedProviders={savedProviders}
        onChange={onProviderChange}
      />
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
      <ModelSelectors hasKey={savedProviders.length > 0} fields={modelFields} />
    </section>
  );
}

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

// The provider chooser already names the provider, so model labels omit its
// repeated prefix.
export function modelLabel(model: string): string {
  const slash = model.indexOf('/');
  return slash < 0 ? model : model.slice(slash + 1);
}

function ModelSelect({
  tier,
  value,
  options,
  groupOf,
  disabled,
  onChange,
}: {
  tier: ModelTier;
  value: string;
  options: string[];
  groupOf?: (model: string) => string;
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
        groupOf={groupOf}
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

// Until catalog or quota reads succeed, disable selections and keep unknown
// usage silent rather than guessing.
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

interface ModelGroup {
  provider: ByokProvider;
  models: string[];
}

function storedChoices(): Record<ModelTier, ModelChoice | null> {
  return {
    worker: getStoredModel('worker'),
    supervisor: getStoredModel('supervisor'),
  };
}

// Choices naming a model the catalog no longer offers would be refused by the
// backend, so drop them once the catalog is known.
function pruneRetiredChoices(catalog: ByokModelCatalog) {
  for (const tier of ['worker', 'supervisor'] as const) {
    const choice = getStoredModel(tier);
    if (choice && !catalog[choice.provider]?.includes(choice.model)) {
      setStoredModel(tier, null);
    }
  }
}

// Every provider with a saved key contributes its models; without keys the
// viewed provider's models can still be chosen ahead of time.
export function useModelFields(
  provider: ByokProvider,
  savedProviders: ByokProvider[],
) {
  const {catalog, freeUsage} = useModelSettingsData();
  const [choices, setChoices] = useState(storedChoices);
  useEffect(() => {
    if (catalog) pruneRetiredChoices(catalog);
    setChoices(storedChoices());
  }, [catalog, savedProviders]);
  const groups: ModelGroup[] = (
    savedProviders.length > 0 ? savedProviders : [provider]
  )
    .map(name => ({provider: name, models: catalog?.[name] ?? []}))
    .filter(group => group.models.length > 0);
  const options = groups.flatMap(group => group.models);
  const groupFor = (model: string) =>
    groups.find(group => group.models.includes(model))?.provider;

  // An unusable or empty choice means the provider default, not a missing
  // selection; the supervisor then follows the worker's provider.
  const usable = (choice: ModelChoice | null) =>
    choice && groupFor(choice.model) === choice.provider ? choice : null;
  const worker = usable(choices.worker);
  const workerProvider =
    worker?.provider ?? fallbackProvider(savedProviders, provider);
  const supervisor = usable(choices.supervisor);
  const defaultOf = (name: ByokProvider) => catalog?.[name]?.[0] ?? '';
  const shown: Record<ModelTier, string> = {
    worker: worker?.model ?? defaultOf(workerProvider),
    supervisor:
      supervisor?.model ?? defaultOf(supervisor?.provider ?? workerProvider),
  };

  // An unchosen tier only displays a fallback that follows the worker, so
  // pin what it shows before the other tier moves provider.
  function onModelChange(tier: ModelTier, model: string) {
    const owner = groupFor(model);
    if (!owner) return;
    const next = {...choices, [tier]: {provider: owner, model}};
    for (const name of ['worker', 'supervisor'] as const) {
      const pinned = shown[name] && groupFor(shown[name]);
      if (!usable(next[name]) && pinned) {
        next[name] = {provider: pinned, model: shown[name]};
      }
      setStoredModel(name, next[name]);
    }
    setChoices(next);
  }

  return {
    options,
    groupOf:
      groups.length > 1
        ? (model: string) => PROVIDER_LABELS[groupFor(model) ?? provider]
        : undefined,
    ...shown,
    freeUsage,
    onModelChange,
  };
}

export type ModelFields = ReturnType<typeof useModelFields>;

// Offline keyless runs spend no free allowance; hide quota text until the real-
// backed count is known.
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

// Model preferences can be chosen before a key exists; headers transmit them
// only with a key.
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
            groupOf={fields.groupOf}
            disabled={disabled}
            onChange={model => fields.onModelChange(tier, model)}
          />
        ))}
      </div>
      {!hasKey && <FreeUsageNote usage={fields.freeUsage} />}
    </>
  );
}

export const PROVIDER_LABELS: Record<ByokProvider, string> = {
  anthropic: 'Anthropic',
  deepseek: 'DeepSeek',
  gemini: 'Gemini',
  openai: 'OpenAI',
  openrouter: 'OpenRouter',
};

// Store the article because pronunciation, not the first letter, determines it;
// derive the displayed provider name from the shared labels.
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

const MENU_GAP_PX = 6;

// Fixed menus escape scroll clipping, but transformed ancestors change their
// origin; measure and subtract that origin instead of assuming the viewport.
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

function groupOptions<T extends string>(
  options: readonly T[],
  groupOf?: (option: T) => string,
): {label: string | null; items: T[]}[] {
  if (!groupOf) return [{label: null, items: [...options]}];
  const sections: {label: string | null; items: T[]}[] = [];
  for (const option of options) {
    const label = groupOf(option);
    const last = sections[sections.length - 1];
    if (last?.label === label) last.items.push(option);
    else sections.push({label, items: [option]});
  }
  return sections;
}

// Real menu buttons preserve Tab/Enter behavior; selecting the current choice
// only dismisses the menu.
export function SettingsSelect<T extends string>({
  value,
  options,
  optionLabel,
  optionNote,
  groupOf,
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
  // Small trailing text, and headings over consecutive options sharing a group.
  optionNote?: (option: T) => string | null;
  groupOf?: (option: T) => string;
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

  // Consume Escape before the dialog listener so dismissing its menu does not
  // also close the dialog.
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
          {groupOptions(options, groupOf).map(section => (
            <div
              key={section.label ?? ''}
              role={section.label ? 'group' : undefined}
              aria-label={section.label ?? undefined}
            >
              {section.label && (
                <div className="ucs-provider-group-label" aria-hidden="true">
                  {section.label}
                </div>
              )}
              {section.items.map(option => (
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
                  {optionNote?.(option) && (
                    <span className="ucs-provider-option-note">
                      {optionNote(option)}
                    </span>
                  )}
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
          ))}
        </div>
      )}
    </div>
  );
}

export function ProviderSelect({
  provider,
  savedProviders,
  onChange,
}: {
  provider: ByokProvider;
  savedProviders: ByokProvider[];
  onChange: (provider: ByokProvider) => void;
}) {
  return (
    <SettingsSelect
      value={provider}
      options={BYOK_PROVIDERS}
      optionLabel={option => PROVIDER_LABELS[option]}
      optionNote={option => (savedProviders.includes(option) ? 'Saved' : null)}
      name="Provider"
      triggerId={TRIGGER_ID}
      labelId={LABEL_ID}
      onChange={onChange}
    />
  );
}

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
