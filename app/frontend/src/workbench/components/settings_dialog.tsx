import type {RefObject} from 'react';
import {useEffect, useRef, useState} from 'react';
import {Icon} from '@/components/icon';
import {
  type ByokProvider,
  getStoredApiKey,
  getStoredApiProvider,
  setStoredApiKey,
  setStoredApiProvider,
} from '@/lib/api_key';
import {useBackgroundInert} from '../hooks/use_background_inert';
import {useEscapeKey} from '../hooks/use_escape_key';
import {useFocusTrap} from '../hooks/use_focus_trap';
import {useRestoreFocusOnClose} from '../hooks/use_restore_focus_on_close';
import {type Mode, useTheme} from '../theme_context';
import {
  AppearanceSection,
  ModelSection,
  SettingsNav,
  type SettingsSection,
} from './settings_dialog_sections';

// The section components, rail entries, and section type live in
// settings_dialog_sections.tsx; re-exported here so callers keep importing
// them from the dialog module.
export {
  SETTINGS_SECTIONS,
  type SettingsSection,
} from './settings_dialog_sections';

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
