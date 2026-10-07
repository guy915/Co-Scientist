import {
  type RefObject,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  useLayoutEffect,
} from 'react';
import {Icon, type IconName} from '@/shared/ui/icon';
import {
  cardClasses,
  Dialog,
  DIALOG_TITLE_CLASSES,
  IconButton,
  Menu,
  MenuItem,
  SectionNav,
  SegmentedControl,
  SelectTrigger,
  TextField,
} from '@/shared/ui';
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
} from '@/shared/lib/client_id';
import {type Mode, useTheme} from '@/shared/hooks/theme_context';
import {
  type ByokModelCatalog,
  type FreeUsage,
  fetchByokModelCatalog,
  fetchFreeUsage,
} from '@/api/system';
import {joinClasses, SETTINGS_FIELD_LABEL_CLASSES} from '@/shared/ui/classes';

const CARD_CLASSES = cardClasses({tone: 'raised', size: 'panel'});
const CARD_TITLE_CLASSES = 'm-0 mb-4 font-gsans text-[1.05rem] font-medium';
const HINT_CLASSES = 'm-0 mt-[0.55rem] text-[0.78rem] text-cosci-muted';

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
      <h2 className={DIALOG_TITLE_CLASSES}>Settings</h2>
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
  // `null` closes the dialog; the last section stays drawn while it fades.
  section: SettingsSection | null;
  onSectionChange: (section: SettingsSection) => void;
  onClose: () => void;
}

export function SettingsDialog({
  section,
  onSectionChange,
  onClose,
}: SettingsDialogProps) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const [shown, setShown] = useState<SettingsSection>(section ?? 'appearance');
  if (section && section !== shown) setShown(section);

  return (
    <Dialog
      open={section !== null}
      onClose={onClose}
      label="Settings"
      size="lg"
      initialFocusRef={closeRef}
    >
      <SettingsDialogHeader onClose={onClose} closeRef={closeRef} />
      <SettingsBody section={shown} onSectionChange={onSectionChange} />
    </Dialog>
  );
}

// Mounted per opening, so the key field rereads storage each time.
function SettingsBody({
  section,
  onSectionChange,
}: {
  section: SettingsSection;
  onSectionChange: (section: SettingsSection) => void;
}) {
  const theme = useTheme();
  const apiKeyField = useApiKeyField();
  return (
    <div className="mt-5 grid min-h-0 flex-1 grid-cols-[13rem_minmax(0,1fr)] gap-6 [@media(max-width:700px)]:mt-[0.9rem] [@media(max-width:700px)]:grid-cols-[minmax(0,1fr)] [@media(max-width:700px)]:grid-rows-[auto_minmax(0,1fr)] [@media(max-width:700px)]:gap-4">
      <SettingsNav section={section} onSectionChange={onSectionChange} />
      <div className="grid min-h-0 gap-4 overflow-y-auto pr-1 [align-content:start]">
        {section === 'appearance' && (
          <AppearanceSection mode={theme.mode} setMode={theme.setMode} />
        )}
        {section === 'model' && <ModelSection {...apiKeyField} />}
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
    <section className={CARD_CLASSES}>
      <h3 className={CARD_TITLE_CLASSES}>Theme</h3>
      <SegmentedControl
        label="Theme"
        value={mode}
        onChange={setMode}
        options={THEME_MODES.map(option => ({
          value: option.mode,
          label: option.label,
          icon: option.icon,
        }))}
      />
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
    <SectionNav
      label="Settings sections"
      value={section}
      onChange={onSectionChange}
      items={SETTINGS_SECTIONS.map(item => ({
        value: item.section,
        label: item.label,
        icon: item.icon,
      }))}
    />
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
      // The menu may be mid scale-in (origin top centre). Offset sizes ignore
      // the scale, and the measured left edge is shifted by half the shrink.
      const rect = el.getBoundingClientRect();
      const width = el.offsetWidth;
      const origin = {
        top: rect.top,
        left: rect.left - (width - rect.width) / 2,
        height: el.offsetHeight,
      };
      const left = align === 'end' ? box.right - width : box.left;
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
  const {menuRef, menuStyle} = useAnchoredMenu(open, container, align);

  return (
    <div
      // An auto track grows to the label's unwrapped width, so a long model id
      // pushed the trigger past the panel instead of ellipsizing.
      className="relative grid w-full grid-cols-[minmax(0,1fr)]"
      ref={container}
    >
      <SelectTrigger
        id={triggerId}
        open={open}
        aria-labelledby={`${labelId} ${triggerId}`}
        disabled={disabled}
        onClick={() => setOpen(current => !current)}
      >
        <span className={truncate ? 'truncate' : undefined}>
          {optionLabel(value)}
        </span>
      </SelectTrigger>
      <Menu
        open={open && !disabled}
        onClose={() => setOpen(false)}
        label={name}
        anchorRefs={[container]}
        menuRef={menuRef}
        style={menuStyle}
        // Absolute menus clip inside the scrolling Settings panel; fixed
        // anchored menus may escape its edges.
        layoutClassName="fixed top-0 left-0 z-40 w-max min-w-full origin-top"
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
                className="px-[0.75rem] pt-[0.4rem] pb-[0.1rem] text-[0.75rem] text-cosci-muted"
                aria-hidden="true"
              >
                {section.label}
              </div>
            )}
            {section.items.map(option => (
              <MenuItem
                key={option}
                kind="radio"
                checked={option === value}
                indicator
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
              </MenuItem>
            ))}
          </div>
        ))}
      </Menu>
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
