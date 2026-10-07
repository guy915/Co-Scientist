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
import {IconButton, TextField} from '@/shared/ui';
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
import {
  SlidingPill,
  useSlidingIndicator,
} from '@/shared/hooks/use_sliding_indicator';
import {
  joinClasses,
  SETTINGS_DIALOG_CLASSES,
  SETTINGS_DIALOG_TITLE_CLASSES,
  SETTINGS_FIELD_CLASSES,
  SETTINGS_FIELD_LABEL_CLASSES,
  SETTINGS_SCRIM_CLASSES,
} from '../classes';

const CARD_CLASSES =
  'rounded-2xl bg-cosci-settings-card-bg px-[1.4rem] pt-5 pb-[1.4rem]';
const CARD_TITLE_CLASSES = 'm-0 mb-4 font-gsans text-[1.05rem] font-medium';
const HINT_CLASSES = 'm-0 mt-[0.55rem] text-[0.78rem] text-cosci-muted';

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
    <header className="flex items-center justify-between gap-4">
      <h2 className={SETTINGS_DIALOG_TITLE_CLASSES}>Settings</h2>
      <IconButton
        ref={closeRef}
        size="md"
        icon="close"
        label="Close settings"
        tooltipPlacement="left"
        onClick={onClose}
      />
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
        className={SETTINGS_SCRIM_CLASSES}
        aria-hidden="true"
        onClick={onClose}
      />
      <div
        className={joinClasses(
          SETTINGS_DIALOG_CLASSES,
          'h-[min(34rem,calc(100dvh-3rem))] w-[min(52rem,calc(100vw-2rem))] px-7 py-6 [@media(max-width:700px)]:h-[calc(100dvh-1.5rem)] [@media(max-width:700px)]:w-[calc(100vw-1.5rem)] [@media(max-width:700px)]:px-4 [@media(max-width:700px)]:py-[1.1rem]',
        )}
        role="dialog"
        aria-modal="true"
        aria-label="Settings"
      >
        <SettingsDialogHeader onClose={onClose} closeRef={closeRef} />
        <div className="mt-5 grid min-h-0 flex-1 grid-cols-[13rem_minmax(0,1fr)] gap-6 [@media(max-width:700px)]:mt-[0.9rem] [@media(max-width:700px)]:grid-cols-[minmax(0,1fr)] [@media(max-width:700px)]:grid-rows-[auto_minmax(0,1fr)] [@media(max-width:700px)]:gap-4">
          <SettingsNav section={section} onSectionChange={onSectionChange} />
          <div className="grid min-h-0 gap-4 overflow-y-auto pr-1 [align-content:start]">
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
  const trackRef = useRef<HTMLDivElement>(null);
  const pill = useSlidingIndicator(trackRef, '[aria-pressed="true"]', mode);
  return (
    <section className={CARD_CLASSES}>
      <h3 className={CARD_TITLE_CLASSES}>Theme</h3>
      <div
        ref={trackRef}
        className="relative grid grid-cols-3 gap-[0.3rem] rounded-[9999px] border border-cosci-border bg-cosci-settings-segment-bg p-[0.18rem]"
        role="group"
        aria-label="Theme"
      >
        <SlidingPill
          box={pill}
          className="ucs-theme-slider pointer-events-none absolute top-[0.18rem] bottom-[0.18rem] left-0 rounded-[9999px] bg-cosci-toggle-on-track"
        />
        {THEME_MODES.map(option => (
          <button
            key={option.mode}
            type="button"
            className={joinClasses(
              'relative flex min-h-[2.6rem] min-w-0 cursor-pointer items-center justify-center gap-[0.45rem] rounded-[9999px] bg-transparent px-[0.44rem] text-[0.875rem] font-semibold [border:0]',
              mode === option.mode
                ? 'text-cosci-selected-row-fg'
                : 'text-cosci-shell-icon focus-visible:bg-cosci-menu-row-hover [&:hover]:bg-cosci-menu-row-hover',
            )}
            aria-pressed={mode === option.mode}
            onClick={() => setMode(option.mode)}
          >
            <Icon
              aria-hidden="true"
              className="text-[1.15rem]"
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
    <p className={HINT_CLASSES}>
      <a
        className="inline-flex items-center gap-1 text-[0.82rem] font-medium text-cosci-blue no-underline focus-visible:underline [&:hover]:underline"
        href={url}
        target="_blank"
        rel="noreferrer"
      >
        Get {article} {PROVIDER_LABELS[provider]} API key
        <Icon
          aria-hidden="true"
          className="text-[0.95rem]"
          name="open_in_new"
        />
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
    <div className="grid gap-4">
      <section className={CARD_CLASSES} aria-labelledby={LABEL_ID}>
        {/* The heading also names the provider menu. */}
        <h3 id={LABEL_ID} className={CARD_TITLE_CLASSES}>
          Provider
        </h3>
        <ProviderSelect
          provider={provider}
          savedProviders={savedProviders}
          onChange={onProviderChange}
        />
        <label
          className={joinClasses(
            'mt-[0.9rem] block',
            SETTINGS_FIELD_LABEL_CLASSES,
          )}
          htmlFor="cosci-settings-api-key"
        >
          {PROVIDER_LABELS[provider]} API key
        </label>
        <TextField
          id="cosci-settings-api-key"
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
      </section>
      <section className={CARD_CLASSES} aria-labelledby="cosci-models-title">
        <h3 id="cosci-models-title" className={CARD_TITLE_CLASSES}>
          Model
        </h3>
        <ModelSelectors
          hasKey={savedProviders.length > 0}
          fields={modelFields}
        />
      </section>
    </div>
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
    <nav
      // Auto margins collapse on overflow; flex-end would spill sections
      // beyond the unreachable left edge on narrow phones.
      className="grid gap-[0.35rem] [align-content:start] [@media(max-width:700px)]:flex [@media(max-width:700px)]:overflow-x-auto [@media(max-width:700px)]:pb-[0.15rem] [@media(max-width:700px)]:[scrollbar-width:none] [@media(max-width:700px)]:[&>:first-child]:ml-auto"
      aria-label="Settings sections"
    >
      {SETTINGS_SECTIONS.map(item => {
        const active = item.section === section;
        return (
          <button
            key={item.section}
            type="button"
            className={joinClasses(
              'flex min-h-11 cursor-pointer items-center gap-[0.72rem] rounded-[9999px] px-4 text-left text-[0.875rem] font-medium [border:0] [@media(max-width:700px)]:min-h-10 [@media(max-width:700px)]:flex-none [@media(max-width:700px)]:gap-[0.4rem] [@media(max-width:700px)]:px-[0.7rem] [@media(max-width:700px)]:text-[0.82rem] [@media(max-width:360px)]:!px-3',
              active
                ? 'bg-cosci-toggle-on-track text-cosci-selected-row-fg'
                : 'bg-transparent text-cosci-fg focus-visible:bg-cosci-menu-row-hover [&:hover]:bg-cosci-menu-row-hover',
            )}
            aria-current={active ? 'true' : undefined}
            onClick={() => onSectionChange(item.section)}
          >
            <Icon
              aria-hidden="true"
              className="flex-none text-[1.25rem] [@media(max-width:360px)]:hidden"
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
    <div className="min-w-0">
      <label
        id={labelId}
        className={joinClasses('block', SETTINGS_FIELD_LABEL_CLASSES)}
        htmlFor={triggerId}
      >
        {TIER_LABELS[tier]}
      </label>
      <SettingsSelect
        value={value}
        options={options}
        optionLabel={modelLabel}
        groupOf={groupOf}
        truncate
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
      : `, ${usage.remaining} of ${usage.limit} left today`;
  return (
    <p className={HINT_CLASSES} role="status">
      Free usage: Express runs only{count}.
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
      <div className="mt-[0.9rem] grid grid-cols-2 gap-3 [@media(max-width:480px)]:grid-cols-[minmax(0,1fr)]">
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
const MENU_EDGE_PX = 16;

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
      el.style.maxHeight = '';
      const box = trigger.getBoundingClientRect();
      el.style.minWidth = `${box.width}px`;
      const origin = el.getBoundingClientRect();
      const left = align === 'end' ? box.right - origin.width : box.left;
      // A long menu flips above its trigger when that side has more room, and
      // scrolls rather than running off the window.
      const below =
        window.innerHeight - box.bottom - MENU_GAP_PX - MENU_EDGE_PX;
      const above = box.top - MENU_GAP_PX - MENU_EDGE_PX;
      const up = origin.height > below && above > below;
      const room = Math.max(up ? above : below, 0);
      const top = up
        ? box.top - MENU_GAP_PX - Math.min(origin.height, room)
        : box.bottom + MENU_GAP_PX;
      const next = {
        top: top - origin.top,
        left: left - origin.left,
        minWidth: box.width,
        maxHeight: room,
      };
      el.style.top = `${next.top}px`;
      el.style.left = `${next.left}px`;
      el.style.maxHeight = `${room}px`;
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
  truncate = false,
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
  truncate?: boolean;
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
    <div
      // An auto track grows to the label's unwrapped width, so a long model id
      // pushed the trigger past the panel instead of ellipsizing.
      className="relative grid w-full grid-cols-[minmax(0,1fr)]"
      ref={container}
      onKeyDown={onKeyDown}
    >
      <button
        type="button"
        id={triggerId}
        className={joinClasses(
          SETTINGS_FIELD_CLASSES,
          'group/trigger flex cursor-pointer items-center justify-between gap-3 text-left disabled:cursor-default disabled:text-cosci-muted [&:hover:not(:disabled)]:bg-cosci-menu-row-hover',
        )}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-labelledby={`${labelId} ${triggerId}`}
        disabled={disabled}
        onClick={() => setOpen(current => !current)}
      >
        <span className={truncate ? 'truncate' : undefined}>
          {optionLabel(value)}
        </span>
        <Icon
          aria-hidden="true"
          className="flex-none text-[1.15rem] text-cosci-muted group-aria-expanded/trigger:[transform:rotate(180deg)]"
          name="expand_more"
        />
      </button>
      {open && !disabled && (
        <div
          ref={menuRef}
          style={menuStyle}
          // Absolute menus clip inside the scrolling Settings panel; fixed
          // anchored menus may escape its edges.
          className="fixed top-0 left-0 z-40 grid w-max min-w-full gap-[0.15rem] overflow-y-auto rounded-xl border border-cosci-border bg-cosci-menu-bg p-[0.35rem] [box-shadow:0_4px_16px_rgb(0_0_0/18%)]"
          role="menu"
          aria-label={name}
        >
          {groupOptions(options, groupOf).map(section => (
            <div
              key={section.label ?? ''}
              // Options must stretch like direct menu children so highlights
              // span the row.
              className="grid"
              role={section.label ? 'group' : undefined}
              aria-label={section.label ?? undefined}
            >
              {section.label && (
                <div
                  className="px-[0.7rem] pt-[0.4rem] pb-[0.1rem] text-[0.75rem] text-cosci-muted"
                  aria-hidden="true"
                >
                  {section.label}
                </div>
              )}
              {section.items.map(option => (
                <button
                  key={option}
                  type="button"
                  role="menuitemradio"
                  aria-checked={option === value}
                  className="flex min-h-[2.4rem] cursor-pointer items-center justify-between gap-5 rounded-lg bg-transparent px-[0.7rem] text-left text-[0.875rem] text-cosci-fg [border:0] focus-visible:bg-cosci-menu-row-hover [&:hover]:bg-cosci-menu-row-hover"
                  onClick={() => {
                    setOpen(false);
                    if (option !== value) onChange(option);
                  }}
                >
                  <span>{optionLabel(option)}</span>
                  {optionNote?.(option) && (
                    <span className="ml-auto text-[0.75rem] text-cosci-muted">
                      {optionNote(option)}
                    </span>
                  )}
                  {option === value && (
                    <Icon
                      aria-hidden="true"
                      className="flex-none text-[1.05rem] text-cosci-blue"
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
