// Core i18n types shared across the locale module.

/** Supported UI locales. */
export type Locale = 'en' | 'he';

/** The default locale used when nothing else is detected. */
export const DEFAULT_LOCALE: Locale = 'en';

/** All supported locales, in display order. */
export const LOCALES: Locale[] = ['en', 'he'];

/** Locales that are written right-to-left. */
export const RTL_LOCALES: ReadonlySet<Locale> = new Set<Locale>(['he']);

/** A flat map of message key -> translated string for one locale. */
export type Messages = Record<string, string>;

/**
 * A translation namespace bundle: the same keys translated per locale.
 * Each dictionary file under `dict/` exports one of these.
 */
export type Bundle = Record<Locale, Messages>;

/** Values that can be interpolated into a message via `{name}` placeholders. */
export type TVars = Record<string, string | number>;

/** A translate function bound to the active locale. */
export type TFunction = (key: string, vars?: TVars) => string;

/** Returns whether a locale reads right-to-left. */
export function isRtl(locale: Locale): boolean {
  return RTL_LOCALES.has(locale);
}

/** Returns the writing direction for a locale. */
export function dirOf(locale: Locale): 'rtl' | 'ltr' {
  return isRtl(locale) ? 'rtl' : 'ltr';
}
