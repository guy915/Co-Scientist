import {useEffect, useState} from 'react';

/**
 * The app's single phone breakpoint. Every layout-mode decision (shell
 * drawer, home stage, ideas master-detail) keys off this query so all
 * surfaces switch at the same width — a second value would create seams
 * where one surface is "mobile" while another is still "desktop".
 */
export const MOBILE_MEDIA_QUERY = '(max-width: 700px)';

/**
 * Imperative check of {@link MOBILE_MEDIA_QUERY} for event handlers and
 * effects. For render-time decisions use {@link useIsMobile}, which
 * re-renders on breakpoint changes. Guarded for environments without
 * `matchMedia` (jsdom, prerender).
 *
 * @returns Whether the viewport currently matches the phone breakpoint.
 */
export function isMobileViewport(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia(MOBILE_MEDIA_QUERY).matches
  );
}

/**
 * Collapses the off-canvas nav drawer, but only on phone viewports where it
 * overlays content. On desktop the rail is persistent and its open/collapsed
 * state is a user preference, so it is left untouched.
 *
 * @param setNavOpen The drawer's open-state setter.
 */
export function closeDrawerIfMobile(setNavOpen: (open: boolean) => void): void {
  if (isMobileViewport()) setNavOpen(false);
}

/**
 * Tracks whether the viewport matches the phone breakpoint.
 *
 * The initial value is read synchronously so the FIRST render already uses
 * the correct layout — the app mounts with createRoot (no hydration), so a
 * desktop-first default would just flash the desktop layout for a frame
 * before an effect corrected it. The effect only subscribes to later
 * breakpoint changes. Guarded for environments without `matchMedia` (jsdom).
 *
 * @returns Whether the query currently matches.
 */
export function useIsMobile(): boolean {
  const [isMobile, setIsMobile] = useState(
    () =>
      typeof window.matchMedia === 'function' &&
      window.matchMedia(MOBILE_MEDIA_QUERY).matches,
  );
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return;
    const mql = window.matchMedia(MOBILE_MEDIA_QUERY);
    const update = () => setIsMobile(mql.matches);
    // Re-read on subscribe: the viewport may have changed between the state
    // initializer (first render) and this effect, the subscription starts.
    update();
    mql.addEventListener('change', update);
    return () => mql.removeEventListener('change', update);
  }, []);
  return isMobile;
}
