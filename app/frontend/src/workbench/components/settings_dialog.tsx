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
import {useToast, type ToastState} from '../hooks/use_toast';
import {type Mode, useTheme} from '../theme_context';
import {
  AffiliationSection,
  AppearanceSection,
  HelpSection,
  ModelSection,
  SettingsNav,
  type SettingsSection,
} from './settings_dialog_sections';

// The section components, rail entries, and section type live in
// settings_dialog_sections.tsx; re-exported here so callers keep importing
// them from the dialog module.
export {
  AffiliationSection,
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
// values) and the brief "Settings saved" confirmation toast.
function useApiKeyField() {
  // Local editable copy of the persisted key; only written back to storage on
  // blur/Enter (see onSave), not on every keystroke.
  const [apiKey, setApiKey] = useState(getStoredApiKey);
  const [provider, setProvider] = useState<ByokProvider>(getStoredApiProvider);
  const {toast: savedToast, setToast: setSavedToast} = useToast(2400);

  // Persists the API key (trimmed; a blank value clears it, see
  // setStoredApiKey) only when it actually changed, then re-syncs local state
  // from storage and shows a brief confirmation toast.
  function onSave() {
    if (apiKey.trim() === getStoredApiKey()) return;
    setStoredApiKey(apiKey);
    setApiKey(getStoredApiKey());
    setSavedToast('Settings saved');
  }

  // Persists the provider choice immediately (a select commits whole
  // values, unlike the free-text key field).
  function onProviderChange(next: ByokProvider) {
    if (next === getStoredApiProvider()) return;
    setStoredApiProvider(next);
    setProvider(getStoredApiProvider());
    setSavedToast('Settings saved');
  }

  return {
    apiKey,
    onApiKeyChange: setApiKey,
    provider,
    onProviderChange,
    onSave,
    savedToast,
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
      {section === 'affiliation' && <AffiliationSection />}
      {section === 'help' && <HelpSection />}
    </div>
  );
}

// The dialog's translucent backdrop. Dismissible dialogs close on a click;
// the locked affiliation chooser has no click-through at all.
function SettingsDialogScrim({
  onClose,
  dismissible,
}: {
  onClose: () => void;
  dismissible: boolean;
}) {
  return (
    <div
      className="ucs-settings-dialog-scrim"
      aria-hidden="true"
      onClick={dismissible ? onClose : undefined}
    />
  );
}

// The brief "Settings saved" confirmation toast, shown only while one is
// pending (see useApiKeyField).
function SettingsDialogToast({toast}: {toast: ToastState | null}) {
  if (!toast) return null;
  return (
    <div className="ucs-settings-toast" role="status">
      {toast.message}
    </div>
  );
}

/**
 * Centered Settings dialog with a section rail (Appearance, Model, Help),
 * matching the reference product's settings window.
 *
 * Doubles as the required first-visit affiliation chooser: passing
 * `dismissible={false}` strips every way out (close button, scrim click,
 * Escape, section rail) so the question has to be answered, and reduces the
 * dialog to the single open section.
 *
 * @param props The active section, change/close callbacks, and whether the
 *   dialog can be dismissed at all.
 */
interface SettingsDialogProps {
  section: SettingsSection;
  onSectionChange: (section: SettingsSection) => void;
  onClose: () => void;
  dismissible?: boolean;
}

// The dialog window itself: header (dismissible only), section rail
// (dismissible only), active section panel, and the save-confirmation
// toast. Split out of SettingsDialog so the component itself stays the
// thin open/close/focus wiring documented there.
interface SettingsDialogWindowProps {
  dismissible: boolean;
  dialogRef: RefObject<HTMLDivElement | null>;
  closeRef: RefObject<HTMLButtonElement | null>;
  section: SettingsSection;
  onSectionChange: (section: SettingsSection) => void;
  onClose: () => void;
  theme: {mode: Mode; setMode: (mode: Mode) => void};
  apiKeyField: ReturnType<typeof useApiKeyField>;
}

// The dialog body: section rail (dismissible only) plus the active section
// panel.
function SettingsDialogBody({
  dismissible,
  section,
  onSectionChange,
  theme,
  apiKeyField,
}: {
  dismissible: boolean;
  section: SettingsSection;
  onSectionChange: (section: SettingsSection) => void;
  theme: {mode: Mode; setMode: (mode: Mode) => void};
  apiKeyField: ReturnType<typeof useApiKeyField>;
}) {
  return (
    <div
      className={
        dismissible
          ? 'ucs-settings-dialog-body'
          : 'ucs-settings-dialog-body ucs-settings-dialog-body--locked'
      }
    >
      {dismissible && (
        <SettingsNav section={section} onSectionChange={onSectionChange} />
      )}
      <SettingsPanel
        section={section}
        theme={theme}
        apiKeyField={apiKeyField}
      />
    </div>
  );
}

function SettingsDialogWindow({
  dismissible,
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
      tabIndex={dismissible ? undefined : -1}
      className={
        dismissible
          ? 'ucs-settings-dialog'
          : 'ucs-settings-dialog ucs-settings-dialog--locked'
      }
      role="dialog"
      aria-modal="true"
      aria-label={dismissible ? 'Settings' : 'Choose your affiliation'}
    >
      {dismissible && (
        <SettingsDialogHeader onClose={onClose} closeRef={closeRef} />
      )}
      <SettingsDialogBody
        dismissible={dismissible}
        section={section}
        onSectionChange={onSectionChange}
        theme={theme}
        apiKeyField={apiKeyField}
      />
      <SettingsDialogToast toast={apiKeyField.savedToast} />
    </div>
  );
}

export function SettingsDialog({
  section,
  onSectionChange,
  onClose,
  dismissible = true,
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
  // (Tab is trapped) or perceive it (it's marked inert) while this is open;
  // both apply in locked mode too, which has the same escape-to-page risk.
  useFocusTrap(rootRef);
  useBackgroundInert(rootRef);
  // Locked, there is no close button to land on, so focus the dialog itself.
  useFocusOnMount(dismissible ? closeRef : dialogRef);
  // A locked dialog has no close affordance at all: no Escape, no scrim
  // click, no close button, and no section rail to navigate away from the
  // question. Leaving any one of them wired is a way past the gate.
  useEscapeKey(onClose, dismissible);

  return (
    <div className="ucs-settings-dialog-root" ref={rootRef}>
      <SettingsDialogScrim onClose={onClose} dismissible={dismissible} />
      <SettingsDialogWindow
        dismissible={dismissible}
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
