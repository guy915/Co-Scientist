import {useEffect, useState} from 'react';

/**
 * Reactive wrapper around window.matchMedia.
 * Returns true while the media query matches, false otherwise.
 * SSR-safe: returns false on the server.
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState<boolean>(() => {
    if (typeof window === 'undefined') return false;
    return window.matchMedia(query).matches;
  });

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const media = window.matchMedia(query);
    setMatches(media.matches);
    const listener = (e: MediaQueryListEvent) => setMatches(e.matches);
    media.addEventListener('change', listener);
    return () => media.removeEventListener('change', listener);
  }, [query]);

  return matches;
}

/** Returns true when the viewport is ≤ 640 px (Tailwind's sm breakpoint). */
export function useIsMobile(): boolean {
  return useMediaQuery('(max-width: 640px)');
}
