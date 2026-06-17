// Pure translation lookup with `{name}` interpolation and graceful fallback.
import {MESSAGES} from './dictionaries';
import {DEFAULT_LOCALE, type Locale, type TVars} from './types';

function interpolate(template: string, vars?: TVars): string {
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (match, name: string) => {
    const value = vars[name];
    return value === undefined ? match : String(value);
  });
}

/**
 * Translate a key for a locale, falling back to English and then the key.
 *
 * Missing keys never throw: they resolve to the English string when present,
 * otherwise to the raw key, so a forgotten translation degrades visibly rather
 * than crashing the UI.
 *
 * @param locale Active locale.
 * @param key Namespaced message key (e.g. `dashboard.title`).
 * @param vars Optional values for `{name}` placeholders.
 * @returns The translated, interpolated string.
 */
export function translate(locale: Locale, key: string, vars?: TVars): string {
  const fromLocale = MESSAGES[locale]?.[key];
  const template = fromLocale ?? MESSAGES[DEFAULT_LOCALE]?.[key] ?? key;
  return interpolate(template, vars);
}
