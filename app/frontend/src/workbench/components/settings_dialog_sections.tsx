import {Icon, type IconName} from '@/components/icon';
import {type ByokProvider} from '@/lib/api_key';
import {type Mode} from '../theme_context';
import {ModelSelectors, useModelFields} from './settings_model_select';
import {
  PROVIDER_KEY_PAGES,
  PROVIDER_LABELS,
  ProviderSelect,
  ProviderSelectLabel,
} from './settings_provider_select';

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
