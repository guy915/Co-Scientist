import {type RefObject, useEffect, useRef, useState} from 'react';
import {Icon, type IconName} from '@/components/icon';
import {
  type ByokProvider,
  getStoredApiKey,
  getStoredApiProvider,
  setStoredApiKey,
  setStoredApiProvider,
} from '@/lib/api_key';
import {
  useBackgroundInert,
  useEscapeKey,
  useFocusTrap,
  useRestoreFocusOnClose,
} from '../hooks/dialog_accessibility';
import {type Mode, useTheme} from '../theme_context';
import {
  ModelSelectors,
  useModelFields,
  PROVIDER_KEY_PAGES,
  PROVIDER_LABELS,
  ProviderSelect,
  ProviderSelectLabel,
} from './settings_model_select';

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

// Active section panel, switching over `section`. `theme` and `apiKeyField`
// forward the two hooks' return values as-is (see useTheme, useApiKeyField).
function SettingsPanel({
  section,
  theme,
  apiKeyField,
}: {
  section: SettingsSection;
  theme: {mode: Mode; setMode: (mode: Mode) => void};
  apiKeyField: ReturnType<typeof useApiKeyField>;
}) {
  return (
    <div className="ucs-settings-dialog-panel">
      {section === 'appearance' && (
        <AppearanceSection mode={theme.mode} setMode={theme.setMode} />
      )}
      {section === 'model' && (
        <ModelSection
          apiKey={apiKeyField.apiKey}
          onApiKeyChange={apiKeyField.onApiKeyChange}
          provider={apiKeyField.provider}
          onProviderChange={apiKeyField.onProviderChange}
          onSave={apiKeyField.onSave}
        />
      )}
    </div>
  );
}

// The dialog's translucent backdrop; a click on it closes the dialog.
function SettingsDialogScrim({onClose}: {onClose: () => void}) {
  return (
    <div
      className="ucs-settings-dialog-scrim"
      aria-hidden="true"
      onClick={onClose}
    />
  );
}

/**
 * Centered Settings dialog with a section rail (Appearance, Model, Help),
 * matching the reference product's settings window.
 *
 * @param props The active section and the change/close callbacks.
 */
interface SettingsDialogProps {
  section: SettingsSection;
  onSectionChange: (section: SettingsSection) => void;
  onClose: () => void;
}

// The dialog window itself: header, section rail, active section panel, and
// the save-confirmation toast. Split out of SettingsDialog so the component
// itself stays the thin open/close/focus wiring documented there.
interface SettingsDialogWindowProps {
  dialogRef: RefObject<HTMLDivElement | null>;
  closeRef: RefObject<HTMLButtonElement | null>;
  section: SettingsSection;
  onSectionChange: (section: SettingsSection) => void;
  onClose: () => void;
  theme: {mode: Mode; setMode: (mode: Mode) => void};
  apiKeyField: ReturnType<typeof useApiKeyField>;
}

// The dialog body: section rail plus the active section panel.
function SettingsDialogBody({
  section,
  onSectionChange,
  theme,
  apiKeyField,
}: {
  section: SettingsSection;
  onSectionChange: (section: SettingsSection) => void;
  theme: {mode: Mode; setMode: (mode: Mode) => void};
  apiKeyField: ReturnType<typeof useApiKeyField>;
}) {
  return (
    <div className="ucs-settings-dialog-body">
      <SettingsNav section={section} onSectionChange={onSectionChange} />
      <SettingsPanel
        section={section}
        theme={theme}
        apiKeyField={apiKeyField}
      />
    </div>
  );
}

function SettingsDialogWindow({
  dialogRef,
  closeRef,
  section,
  onSectionChange,
  onClose,
  theme,
  apiKeyField,
}: SettingsDialogWindowProps) {
  return (
    <div
      ref={dialogRef}
      className="ucs-settings-dialog"
      role="dialog"
      aria-modal="true"
      aria-label="Settings"
    >
      <SettingsDialogHeader onClose={onClose} closeRef={closeRef} />
      <SettingsDialogBody
        section={section}
        onSectionChange={onSectionChange}
        theme={theme}
        apiKeyField={apiKeyField}
      />
    </div>
  );
}

export function SettingsDialog({
  section,
  onSectionChange,
  onClose,
}: SettingsDialogProps) {
  const theme = useTheme();
  const closeRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
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
      <SettingsDialogScrim onClose={onClose} />
      <SettingsDialogWindow
        dialogRef={dialogRef}
        closeRef={closeRef}
        section={section}
        onSectionChange={onSectionChange}
        onClose={onClose}
        theme={theme}
        apiKeyField={apiKeyField}
      />
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
