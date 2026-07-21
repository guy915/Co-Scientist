import type {RefObject} from 'react';
import {useEffect, useRef, useState} from 'react';
import {Icon, type IconName} from '@/components/icon';
import {getStoredApiKey, setStoredApiKey} from '@/lib/api_key';
import {useAudience} from '../audience_context';
import {AUDIENCE_OPTIONS} from '../audience_content';
import {useToast} from '../hooks/use_toast';
import {type Mode, useTheme} from '../theme_context';

/**
 * The dialog's section rail options; also the type of the currently-open
 * section, controlled by the parent (see the `section`/`onSectionChange`
 * props below).
 */
export type SettingsSection = 'appearance' | 'model' | 'affiliation' | 'help';

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
  {section: 'affiliation', icon: 'assignment', label: 'Affiliation'},
  {section: 'help', icon: 'help', label: 'Help'},
];

// Static question/answer copy rendered as collapsible <details> in the Help
// section.
const FAQ: {question: string; answer: string}[] = [
  {
    question: 'What is Co-Scientist?',
    answer:
      'A multi-agent workspace that generates, debates, and ranks research ' +
      'hypotheses for a goal you set. A team of agents proposes ideas, ' +
      'reviews them, and runs a tournament so the strongest directions rise ' +
      'to the top.',
  },
  {
    question: 'How do I start a run?',
    answer:
      'From the home screen, describe your research goal in the composer and ' +
      'send it. Co-Scientist confirms the setup, then the agents generate and ' +
      'evaluate ideas. Follow progress and results in the run view.',
  },
  {
    question: 'Where does my API key go?',
    answer:
      'The key you enter under Model is stored only in this browser and is ' +
      'never uploaded. Clearing your browser storage removes it.',
  },
  {
    question: 'Which model does it use?',
    answer:
      'Runs use the provider configured for the deployment (DeepSeek by ' +
      'default). Model selection is managed server-side for now.',
  },
];

// Appearance section: theme mode segmented control (system/light/dark).
function AppearanceSection({
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

// Static "Get a DeepSeek API key" link shown below the key field.
function ApiKeyHint() {
  return (
    <p className="ucs-settings-field-hint">
      <a
        className="ucs-settings-field-link"
        href="https://platform.deepseek.com/api_keys"
        target="_blank"
        rel="noreferrer"
      >
        Get a DeepSeek API key
        <Icon aria-hidden="true" name="open_in_new" />
      </a>
    </p>
  );
}

// Model section: browser-local API key entry, saved on blur or Enter.
function ModelSection({
  apiKey,
  onApiKeyChange,
  onSave,
}: {
  apiKey: string;
  onApiKeyChange: (value: string) => void;
  onSave: () => void;
}) {
  return (
    <section className="ucs-settings-card">
      <h3 className="ucs-settings-card-title">Model</h3>
      <label
        className="ucs-settings-field-label"
        htmlFor="cosci-settings-api-key"
      >
        DeepSeek API key
      </label>
      <input
        id="cosci-settings-api-key"
        className="ucs-settings-field-input"
        type="password"
        autoComplete="off"
        placeholder="Paste your DeepSeek API key"
        value={apiKey}
        onChange={event => onApiKeyChange(event.target.value)}
        onBlur={onSave}
        onKeyDown={event => {
          if (event.key === 'Enter') onSave();
        }}
      />
      <ApiKeyHint />
    </section>
  );
}

// Section rail: list of nav buttons for switching between the dialog's
// sections (see SETTINGS_SECTIONS above), highlighting whichever is
// currently active.
function SettingsNav({
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

// Help section: static product blurb plus a collapsible FAQ list.
function HelpSection() {
  return (
    <section className="ucs-settings-card">
      <h3 className="ucs-settings-card-title">Help</h3>
      <p className="ucs-settings-card-copy">
        Co-Scientist is a multi-agent workspace for generating and
        pressure-testing research hypotheses. Set a research goal and a team of
        agents proposes ideas, reviews them, and ranks the strongest directions
        tournament-style.
      </p>
      <div className="ucs-faq">
        {FAQ.map(item => (
          <details key={item.question} className="ucs-faq-item">
            <summary className="ucs-faq-question">
              <span>{item.question}</span>
              <Icon
                aria-hidden="true"
                className="ucs-faq-chevron"
                name="expand_more"
              />
            </summary>
            <p className="ucs-faq-answer">{item.answer}</p>
          </details>
        ))}
      </div>
    </section>
  );
}

/**
 * Settings section letting the user change their declared affiliation. Also
 * serves as the first-visit chooser: AudienceGate opens Settings here when no
 * audience has been picked yet.
 */
export function AffiliationSection() {
  const {audience, setAudience} = useAudience();
  // Nothing is preselected while the answer is unset: the chooser is a
  // required first-visit question (see AudienceGate), so showing a default
  // already ticked would read as "answered" and invite closing past it.
  const selected = audience;
  const required = audience === null;
  return (
    <section className="ucs-settings-card">
      <h3 className="ucs-settings-card-title">Affiliation</h3>
      <p className="ucs-settings-card-copy">
        {required
          ? 'Tell us how you use Co-Scientist so the workspace can be ' +
            'tailored to you. You can change this later in Settings.'
          : 'This tailors the workspace to how you use Co-Scientist. You can ' +
            'change it here at any time.'}
      </p>
      <div className="ucs-affiliation-group">
        {AUDIENCE_OPTIONS.map(option => (
          <label key={option.value} className="ucs-affiliation-option">
            <input
              className="ucs-affiliation-input"
              type="radio"
              name="cosci-affiliation"
              value={option.value}
              checked={selected === option.value}
              onChange={() => setAudience(option.value)}
            />
            <span className="ucs-affiliation-title">{option.title}</span>
            <span className="ucs-affiliation-blurb">{option.blurb}</span>
          </label>
        ))}
      </div>
    </section>
  );
}

// Moves focus to `ref`'s element once on mount, so keyboard/screen-reader
// users land inside a newly opened dialog rather than on whatever was
// focused behind it.
function useFocusOnMount(ref: RefObject<HTMLElement | null>) {
  useEffect(() => {
    ref.current?.focus();
  }, [ref]);
}

// Global Escape-to-close, active for as long as the caller stays mounted.
// `enabled` is false for a locked dialog, which has no close path at all.
function useEscapeKey(onClose: () => void, enabled: boolean) {
  useEffect(() => {
    if (!enabled) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [onClose, enabled]);
}

// Model section's API key field: a local editable copy of the persisted key
// (written back to storage only on blur/Enter, not every keystroke) plus the
// brief "Settings saved" confirmation toast.
function useApiKeyField() {
  // Local editable copy of the persisted key; only written back to storage on
  // blur/Enter (see onSave), not on every keystroke.
  const [apiKey, setApiKey] = useState(getStoredApiKey);
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

  return {apiKey, onApiKeyChange: setApiKey, onSave, savedToast};
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
  apiKeyField: {
    apiKey: string;
    onApiKeyChange: (value: string) => void;
    onSave: () => void;
  };
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
          onSave={apiKeyField.onSave}
        />
      )}
      {section === 'affiliation' && <AffiliationSection />}
      {section === 'help' && <HelpSection />}
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
export function SettingsDialog({
  section,
  onSectionChange,
  onClose,
  dismissible = true,
}: {
  section: SettingsSection;
  onSectionChange: (section: SettingsSection) => void;
  onClose: () => void;
  dismissible?: boolean;
}) {
  const theme = useTheme();
  const closeRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const apiKeyField = useApiKeyField();

  // Locked, there is no close button to land on, so focus the dialog itself.
  useFocusOnMount(dismissible ? closeRef : dialogRef);
  // A locked dialog has no close affordance at all: no Escape, no scrim
  // click, no close button, and no section rail to navigate away from the
  // question. Leaving any one of them wired is a way past the gate.
  useEscapeKey(onClose, dismissible);

  return (
    <div className="ucs-settings-dialog-root">
      <div
        className="ucs-settings-dialog-scrim"
        aria-hidden="true"
        onClick={dismissible ? onClose : undefined}
      />
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
        {apiKeyField.savedToast && (
          <div className="ucs-settings-toast" role="status">
            {apiKeyField.savedToast.message}
          </div>
        )}
      </div>
    </div>
  );
}
