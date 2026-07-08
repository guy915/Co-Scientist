import {useEffect, useRef, useState} from 'react';
import {Icon, type IconName} from '@/components/icon';
import {getStoredApiKey, setStoredApiKey} from '@/lib/api_key';
import {useToast} from '../hooks/use_toast';
import {useTheme} from '../theme_context';

// The dialog's section rail options; also the type of the currently-open
// section, controlled by the parent (see the `section`/`onSectionChange`
// props below).
export type SettingsSection = 'appearance' | 'model' | 'help';

type ThemeMode = 'system' | 'light' | 'dark';

// Options rendered in the Appearance section's theme segmented control.
// Selecting one calls useTheme()'s setMode, which persists the choice (see
// theme_context.tsx) and updates the resolved MD3 theme immediately.
const THEME_MODES: Array<{mode: ThemeMode; icon: IconName; label: string}> = [
  {mode: 'system', icon: 'computer', label: 'System'},
  {mode: 'light', icon: 'light_mode', label: 'Light'},
  {mode: 'dark', icon: 'dark_mode', label: 'Dark'},
];

// Section-rail entries, in display order.
const SECTIONS: Array<{
  section: SettingsSection;
  icon: IconName;
  label: string;
}> = [
  {section: 'appearance', icon: 'palette', label: 'Appearance'},
  {section: 'model', icon: 'neurology', label: 'Model'},
  {section: 'help', icon: 'help', label: 'Help'},
];

// Static question/answer copy rendered as collapsible <details> in the Help
// section.
const FAQ: Array<{question: string; answer: string}> = [
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
  mode: ThemeMode;
  setMode: (mode: ThemeMode) => void;
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
    </section>
  );
}

// Help section: static product blurb plus a collapsible FAQ list.
function HelpSection() {
  return (
    <section className="ucs-settings-card">
      <h3 className="ucs-settings-card-title">Help</h3>
      <p className="ucs-settings-card-copy">
        Co-Scientist is a multi-agent workspace for generating and
        pressure-testing research hypotheses. Set a research goal and a team
        of agents proposes ideas, reviews them, and ranks the strongest
        directions tournament-style.
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
 * Centered Settings dialog with a section rail (Appearance, Model, Help),
 * matching the reference product's settings window.
 *
 * @param props The active section plus change/close callbacks.
 */
export function SettingsDialog({
  section,
  onSectionChange,
  onClose,
}: {
  section: SettingsSection;
  onSectionChange: (section: SettingsSection) => void;
  onClose: () => void;
}) {
  const {mode, setMode} = useTheme();
  const closeRef = useRef<HTMLButtonElement>(null);
  // Local editable copy of the persisted key; only written back to storage on
  // blur/Enter (see saveApiKey), not on every keystroke.
  const [apiKey, setApiKey] = useState(getStoredApiKey);
  const {toast: savedToast, setToast: setSavedToast} = useToast(2400);

  // Move focus to the close button on open, so keyboard/screen-reader users
  // land inside the dialog rather than on whatever was focused behind it.
  useEffect(() => {
    closeRef.current?.focus();
  }, []);

  // Global Escape-to-close, active for as long as the dialog is mounted.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [onClose]);

  // Persists the API key (trimmed; a blank value clears it, see
  // setStoredApiKey) only when it actually changed, then re-syncs local state
  // from storage and shows a brief confirmation toast.
  function saveApiKey() {
    if (apiKey.trim() === getStoredApiKey()) return;
    setStoredApiKey(apiKey);
    setApiKey(getStoredApiKey());
    setSavedToast('Settings saved');
  }

  return (
    <div className="ucs-settings-dialog-root">
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
        <div className="ucs-settings-dialog-body">
          <nav
            className="ucs-settings-dialog-nav"
            aria-label="Settings sections"
          >
            {SECTIONS.map(item => {
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
          <div className="ucs-settings-dialog-panel">
            {section === 'appearance' && (
              <AppearanceSection mode={mode} setMode={setMode} />
            )}
            {section === 'model' && (
              <ModelSection
                apiKey={apiKey}
                onApiKeyChange={setApiKey}
                onSave={saveApiKey}
              />
            )}
            {section === 'help' && <HelpSection />}
          </div>
        </div>
        {savedToast && (
          <div className="ucs-settings-toast" role="status">
            {savedToast.message}
          </div>
        )}
      </div>
    </div>
  );
}
