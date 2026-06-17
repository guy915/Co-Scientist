import {describe, it, expect} from 'vitest';
import {translate} from './translate';
import {MESSAGES} from './dictionaries';
import {browserLocale, localeFromLanguageTag} from './detect';
import {dirOf, isRtl, LOCALES} from './types';

describe('translate', () => {
  it('returns the locale string when present', () => {
    expect(translate('en', 'app.name')).toBe('Co-Scientist');
    // Hebrew nav label differs from English.
    expect(translate('he', 'nav.dashboard')).not.toBe(
      translate('en', 'nav.dashboard'),
    );
  });

  it('interpolates {placeholders}', () => {
    expect(translate('en', 'footer.copyright', {year: 2026})).toContain('2026');
  });

  it('falls back to English then to the raw key for missing entries', () => {
    // A key that exists only conceptually: unknown keys echo back.
    expect(translate('he', 'totally.unknown.key')).toBe('totally.unknown.key');
  });
});

describe('dictionaries', () => {
  it('keeps Hebrew key parity with English', () => {
    const enKeys = Object.keys(MESSAGES.en).sort();
    const heKeys = Object.keys(MESSAGES.he).sort();
    // Every English key should have a Hebrew translation and vice versa.
    const missingInHe = enKeys.filter(k => !(k in MESSAGES.he));
    const missingInEn = heKeys.filter(k => !(k in MESSAGES.en));
    expect(missingInHe).toEqual([]);
    expect(missingInEn).toEqual([]);
  });

  it('has non-empty values for every locale', () => {
    for (const locale of LOCALES) {
      for (const [key, value] of Object.entries(MESSAGES[locale])) {
        expect(value, `${locale}:${key}`).not.toBe('');
      }
    }
  });
});

describe('detection helpers', () => {
  it('maps language tags to supported locales', () => {
    expect(localeFromLanguageTag('he-IL')).toBe('he');
    expect(localeFromLanguageTag('he')).toBe('he');
    expect(localeFromLanguageTag('en-US')).toBe('en');
    expect(localeFromLanguageTag('fr-FR')).toBeNull();
    expect(localeFromLanguageTag(undefined)).toBeNull();
  });

  it('reads the browser language', () => {
    const original = navigator.languages;
    Object.defineProperty(navigator, 'languages', {
      value: ['he-IL', 'en-US'],
      configurable: true,
    });
    expect(browserLocale()).toBe('he');
    Object.defineProperty(navigator, 'languages', {
      value: original,
      configurable: true,
    });
  });
});

describe('direction', () => {
  it('marks Hebrew as RTL and English as LTR', () => {
    expect(isRtl('he')).toBe(true);
    expect(isRtl('en')).toBe(false);
    expect(dirOf('he')).toBe('rtl');
    expect(dirOf('en')).toBe('ltr');
  });
});
