import {useEffect} from 'react';
import {
  type NavigateFunction,
  useLocation,
  useNavigate,
} from 'react-router-dom';

/**
 * Global keyboard shortcuts:
 *   g n  -> /
 *   ←/→  -> cycle tabs on /runs/:id
 * Inputs and textareas are ignored so typing doesn't trigger the bindings.
 */
// Arrow-key cycling order; must match the tab routes RunDetail renders.
const TABS = ['details', 'learning', 'overview', 'ideas'] as const;

// Keys that cycle tabs; any other key is left alone by nextTabPath.
const TAB_CYCLE_KEYS: readonly string[] = ['ArrowLeft', 'ArrowRight'];

// True when the key event originated in an editable control (input,
// textarea, contenteditable), in which case shortcuts must not fire.
function isTextEditingTarget(t: EventTarget | null): boolean {
  const el = t as HTMLElement | null;
  if (!el) return false;
  const tag = el.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || el.isContentEditable;
}

// True when the shortcuts must not fire at all: typing in an editable
// control, or a modifier held (leaving browser/OS shortcuts alone).
function shouldIgnoreShortcut(e: KeyboardEvent): boolean {
  return isTextEditingTarget(e.target) || e.metaKey || e.ctrlKey || e.altKey;
}

// True when this keydown is the "n" completing a "g n" sequence, i.e. it
// arrives within 800ms of the last "g" press.
function isHomeShortcut(key: string, lastG: number, now: number): boolean {
  return now - lastG < 800 && key === 'n';
}

// Matches a /runs/:id(/:tab) pathname, capturing the run id and optional tab
// segment, or null when the pathname doesn't look like a run route.
function matchRunRoute(pathname: string): RegExpMatchArray | null {
  return pathname.match(/^\/runs\/([^/]+)(?:\/(.+))?$/);
}

// Parses a /runs/:id(/:tab) route into the run id and current tab, or null
// when the pathname isn't a run route or is the legacy '/runs/new' path.
// Unknown or missing tab segments count as the default 'details'.
function parseRunTabRoute(
  pathname: string,
): {id: string; current: (typeof TABS)[number]} | null {
  const m = matchRunRoute(pathname);
  if (!m) return null;
  const id = m[1];
  if (id === 'new') return null; // legacy path, not a real run
  const current = (
    m[2] && (TABS as readonly string[]).includes(m[2]) ? m[2] : 'details'
  ) as (typeof TABS)[number];
  return {id, current};
}

// Index of the tab adjacent to `currentIdx` in the given arrow direction,
// clamped at the ends of TABS rather than wrapping around.
function adjacentTabIndex(currentIdx: number, key: string): number {
  return key === 'ArrowRight'
    ? Math.min(TABS.length - 1, currentIdx + 1)
    : Math.max(0, currentIdx - 1);
}

// Resolves an ArrowLeft/ArrowRight press on a /runs/:id(/:tab) route to the
// path for the adjacent tab, or null when the key/route doesn't apply or the
// current tab is already at that end of TABS (no wraparound).
function nextTabPath(pathname: string, key: string): string | null {
  if (!TAB_CYCLE_KEYS.includes(key)) return null;
  const route = parseRunTabRoute(pathname);
  if (!route) return null;
  const idx = TABS.indexOf(route.current);
  const next = adjacentTabIndex(idx, key);
  if (next === idx) return null;
  const nextTab = TABS[next];
  // 'details' navigates to the bare id, which the router redirects to
  // /runs/:id/details (the canonical default-tab URL).
  return `/runs/${route.id}/${nextTab === 'details' ? '' : nextTab}`;
}

// Builds the document keydown handler for the given navigation callback and
// current pathname. Pulled out of the effect below so the effect only wires
// up listener registration/cleanup; this factory decides what a keypress
// means. `lastG` (the timestamp of the last bare "g" press) lives in the
// returned closure rather than a ref, so it resets whenever a fresh handler
// is built -- i.e. on every navigate/pathname change, matching the original
// per-effect-run reset.
function createKeyDownHandler(
  navigate: NavigateFunction,
  pathname: string,
): (e: KeyboardEvent) => void {
  let lastG = 0;
  return e => {
    if (shouldIgnoreShortcut(e)) return;

    const now = Date.now();
    // Two-key "g n" sequence (Vim-style).
    if (e.key === 'g') {
      lastG = now;
      return;
    }
    // The prefix is only honored within 800ms, and any non-"g" key
    // consumes it so a stale "g" can't pair with a much later "n".
    const wasG = isHomeShortcut(e.key, lastG, now);
    lastG = 0;

    if (wasG) {
      e.preventDefault();
      void navigate('/');
      return;
    }

    // Tab nav while on a run page.
    const path = nextTabPath(pathname, e.key);
    if (path) {
      e.preventDefault();
      void navigate(path);
    }
  };
}

/**
 * Registers the app-wide keyboard shortcuts for the lifetime of the calling
 * component.
 */
export function useGlobalShortcuts() {
  const navigate = useNavigate();
  const location = useLocation();

  // Re-runs (removing and re-adding the single document keydown listener) on
  // every pathname change so the handler closure always sees the current
  // route; cleanup on unmount removes the last listener.
  useEffect(() => {
    const onKeyDown = createKeyDownHandler(navigate, location.pathname);
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [navigate, location.pathname]);
}
