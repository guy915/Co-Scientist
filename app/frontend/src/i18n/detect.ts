// Locale detection: stored override -> browser language -> geo-IP (Israel).
import {DEFAULT_LOCALE, LOCALES, type Locale} from './types';

export const STORAGE_KEY = 'coscientist-locale';

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string) || '';

function isLocale(value: string | null): value is Locale {
  return value !== null && (LOCALES as string[]).includes(value);
}

/** Read a previously chosen locale from localStorage, if any. */
export function storedLocale(): Locale | null {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return isLocale(stored) ? stored : null;
  } catch {
    return null;
  }
}

/** Persist the user's explicit locale choice. */
export function persistLocale(locale: Locale): void {
  try {
    localStorage.setItem(STORAGE_KEY, locale);
  } catch {
    /* ignore */
  }
}

/** Map a BCP-47 language tag (e.g. `he-IL`) to a supported locale, or null. */
export function localeFromLanguageTag(tag: string | undefined): Locale | null {
  if (!tag) return null;
  const base = tag.toLowerCase().split('-')[0];
  return (LOCALES as string[]).includes(base) ? (base as Locale) : null;
}

/** Detect a locale from the browser's configured languages. */
export function browserLocale(): Locale | null {
  if (typeof navigator === 'undefined') return null;
  const tags = navigator.languages?.length
    ? navigator.languages
    : [navigator.language];
  for (const tag of tags) {
    const locale = localeFromLanguageTag(tag);
    if (locale) return locale;
  }
  return null;
}

/**
 * Best synchronous guess available at first paint: stored override, then the
 * browser language, then the default. Geo-IP runs asynchronously afterwards.
 */
export function initialLocale(): Locale {
  return storedLocale() ?? browserLocale() ?? DEFAULT_LOCALE;
}

/**
 * Ask the backend to suggest a locale from the request origin (e.g. Hebrew for
 * visitors in Israel). Best-effort: any failure resolves to null.
 */
export async function geoLocale(): Promise<Locale | null> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/geo`);
    if (!res.ok) return null;
    const data = (await res.json()) as {locale?: string | null};
    return isLocale(data.locale ?? null) ? (data.locale as Locale) : null;
  } catch {
    return null;
  }
}
