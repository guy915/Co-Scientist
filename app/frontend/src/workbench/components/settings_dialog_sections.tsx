import {Icon, type IconName} from '@/components/icon';
import {type ByokProvider} from '@/lib/api_key';
import {useAudience} from '../audience_context';
import {AUDIENCE_OPTIONS} from '../audience_content';
import {type Mode} from '../theme_context';
import {
  PROVIDER_LABELS,
  ProviderSelect,
  ProviderSelectLabel,
} from './settings_provider_select';

/**
 * The dialog's section rail options; also the type of the currently-open
 * section, controlled by the parent (see the `section`/`onSectionChange`
 * props on SettingsDialog in settings_dialog.tsx).
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
      'send it. Co-Scientist confirms the setup, then the agents generate ' +
      'and ' +
      'evaluate ideas. Follow progress and results in the run view.',
  },
  {
    question: 'Where does my API key go?',
    answer:
      'The key you enter under Model is stored in this browser and sent to ' +
      'the server when you start a run or chat with the Agent. The server ' +
      'checks it with the provider, then stores it encrypted for that run ' +
      'only and never returns it. Clearing your browser storage removes the ' +
      'local copy.',
  },
  {
    question: 'Which model does it use?',
    answer:
      'Runs use the model configured for the deployment (DeepSeek by ' +
      'default). When you add your own API key under Model, runs use your ' +
      "provider's default model instead.",
  },
  {
    question: 'Are there keyboard shortcuts?',
    answer:
      'Press g then n from anywhere to jump to the home screen. On a ' +
      "run's report page, the left and right arrow keys move between " +
      "tabs. Shortcuts don't fire while you're typing in a text field or " +
      'using another control.',
  },
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

// Hint under the key field: a key-source link for DeepSeek (the default),
// plus what happens to the key once saved.
function ApiKeyHint({provider}: {provider: ByokProvider}) {
  return (
    <p className="ucs-settings-field-hint">
      {provider === 'deepseek' && (
        <a
          className="ucs-settings-field-link"
          href="https://platform.deepseek.com/api_keys"
          target="_blank"
          rel="noreferrer"
        >
          Get a DeepSeek API key
          <Icon aria-hidden="true" name="open_in_new" />
        </a>
      )}
      <span className="ucs-settings-hint-copy">
        Sent with run requests; the server validates it and stores it encrypted
        for that run only.
      </span>
    </p>
  );
}

// Model section: bring-your-own-key provider choice and key entry. The key
// saves on blur or Enter; the provider persists on change.
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

// Help section: static product blurb plus a collapsible FAQ list.
export function HelpSection() {
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
