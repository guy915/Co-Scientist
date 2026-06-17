import '@material/web/iconbutton/icon-button.js';
import '@material/web/icon/icon.js';
import {useLocale} from '@/i18n';
import type {Locale} from '@/i18n';

const NEXT: Record<Locale, Locale> = {en: 'he', he: 'en'};

// Short label shown on the toggle: the language it will switch *to*.
const SWITCH_TO_LABEL: Record<Locale, string> = {en: 'EN', he: 'עב'};

/**
 * Renders a compact button that toggles the UI between English and Hebrew.
 */
export function LanguageSwitcher() {
  const {locale, setLocale, t} = useLocale();
  const next = NEXT[locale];
  const label = t('nav.language');
  return (
    <md-icon-button
      onclick={(() => setLocale(next)) as EventListener}
      aria-label={label}
      title={label}
    >
      <span
        aria-hidden="true"
        style={{
          fontSize: '0.75rem',
          fontWeight: 600,
          lineHeight: 1,
          letterSpacing: '0.02em',
        }}
      >
        {SWITCH_TO_LABEL[locale]}
      </span>
    </md-icon-button>
  );
}
