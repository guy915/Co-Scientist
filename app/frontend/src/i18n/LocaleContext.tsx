import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useState,
} from 'react';
import {
  browserLocale,
  geoLocale,
  initialLocale,
  persistLocale,
  storedLocale,
} from './detect';
import {translate} from './translate';
import {DEFAULT_LOCALE, dirOf, type Locale, type TFunction} from './types';

interface LocaleContextValue {
  /** Active locale. */
  locale: Locale;
  /** Writing direction for the active locale. */
  dir: 'rtl' | 'ltr';
  /** Whether the user has explicitly chosen a locale. */
  isExplicit: boolean;
  /** Set and persist the active locale. */
  setLocale: (locale: Locale) => void;
  /** Translate a key in the active locale. */
  t: TFunction;
}

const LocaleContext = createContext<LocaleContextValue | null>(null);

/**
 * Provides the active locale, persists explicit choices, runs auto-detection
 * (browser language then geo-IP), and keeps the document `lang`/`dir` in sync.
 *
 * @param props The subtree that consumes the locale context.
 */
export function LocaleProvider({children}: {children: ReactNode}) {
  const [locale, setLocaleState] = useState<Locale>(initialLocale);
  const [isExplicit, setIsExplicit] = useState<boolean>(
    () => storedLocale() !== null,
  );

  // Keep the document element's language and direction aligned with the locale
  // so native text rendering, scrollbars, and CSS logical properties flip.
  useLayoutEffect(() => {
    const root = document.documentElement;
    root.lang = locale;
    root.dir = dirOf(locale);
  }, [locale]);

  // Auto-detect once on mount when the user hasn't made an explicit choice.
  // The synchronous guess already honored the browser language; here we ask the
  // backend whether the visitor's region implies a different default.
  useEffect(() => {
    if (isExplicit) return;
    // The browser language is an authoritative signal — if it already names a
    // supported locale, trust it and skip the network round-trip.
    if (browserLocale() !== null) return;
    let cancelled = false;
    void geoLocale().then(detected => {
      if (!cancelled && detected && !storedLocale()) {
        setLocaleState(detected);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [isExplicit]);

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next);
    setIsExplicit(true);
    persistLocale(next);
  }, []);

  const value = useMemo<LocaleContextValue>(
    () => ({
      locale,
      dir: dirOf(locale),
      isExplicit,
      setLocale,
      t: (key, vars) => translate(locale, key, vars),
    }),
    [locale, isExplicit, setLocale],
  );

  return (
    <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>
  );
}

/** Returns the full locale context from {@link LocaleProvider}. */
export function useLocale(): LocaleContextValue {
  const ctx = useContext(LocaleContext);
  if (!ctx) throw new Error('useLocale used outside LocaleProvider');
  return ctx;
}

/**
 * Returns the translate function bound to the active locale.
 *
 * Unlike {@link useLocale}, this tolerates being called outside a
 * {@link LocaleProvider}: it falls back to the default locale instead of
 * throwing, so components remain renderable in isolation (e.g. unit tests).
 *
 * @returns A `t(key, vars?)` function.
 */
export function useT(): TFunction {
  const ctx = useContext(LocaleContext);
  if (!ctx) return (key, vars) => translate(DEFAULT_LOCALE, key, vars);
  return ctx.t;
}
