import {useEffect} from 'react';
import {
  type NavigateFunction,
  useLocation,
  useNavigate,
} from 'react-router-dom';
import {TABS, normalizeTab, type TabName} from '../run_tabs';

/**
 * Global keyboard shortcuts, bound on `document` regardless of what has
 * focus (this is deliberate -- see the ArrowLeft/ArrowRight note below, not
 * a roving-tabindex widget reimplemented at the document level):
 *   g n  -> /
 *   ←/→  -> cycle tabs on /runs/:id
 * Inputs, textareas, and widgets that already own arrow-key behavior are
 * exempted so typing or operating a control doesn't trigger the bindings.
 */
// Keys that cycle tabs; any other key is left alone by nextTabPath.
const TAB_CYCLE_KEYS: readonly string[] = ['ArrowLeft', 'ArrowRight'];

// ARIA widget roles that consume arrow keys themselves (an open listbox/
// combobox moves its highlighted option, a slider changes its value, a
// radiogroup moves selection between radios) -- the global tab-cycle
// shortcut must not steal them out from under the widget.
const ARROW_OWNING_WIDGET_ROLES: readonly string[] = [
  'listbox',
  'combobox',
  'slider',
  'radiogroup',
];

// True when the key event originated in an editable control (input,
// textarea, contenteditable), in which case shortcuts must not fire.
function isTextEditingTarget(t: EventTarget | null): boolean {
  const el = t as HTMLElement | null;
  if (!el) return false;
  const tag = el.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || el.isContentEditable;
}

// True when the key event originated on a native <select> or an ARIA widget
// that owns its own arrow-key behavior (see ARROW_OWNING_WIDGET_ROLES) --
// e.g. the bring-your-own-key provider <select>, whose Left/Right cycles its
// options and must not also advance the report tab underneath it.
function isWidgetTarget(t: EventTarget | null): boolean {
  if (!(t instanceof Element)) return false;
  if (t.tagName === 'SELECT') return true;
  const role = t.getAttribute('role');
  return role !== null && ARROW_OWNING_WIDGET_ROLES.includes(role);
}

// True when the shortcuts must not fire at all: typing in an editable
// control, operating a widget that owns its own arrow keys, or a modifier
// held (leaving browser/OS shortcuts alone).
function shouldIgnoreShortcut(e: KeyboardEvent): boolean {
  return (
    isTextEditingTarget(e.target) ||
    isWidgetTarget(e.target) ||
    e.metaKey ||
    e.ctrlKey ||
    e.altKey
  );
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
// The tab segment is resolved through the shared normalizeTab, so aliases
// (e.g. 'hypotheses' -> 'ideas') and unknown/missing segments land on the same
// tab RunDetail actually renders.
function parseRunTabRoute(
  pathname: string,
): {id: string; current: TabName} | null {
  const m = matchRunRoute(pathname);
  if (!m) return null;
  const id = m[1];
  if (id === 'new') return null; // legacy path, not a real run
  return {id, current: normalizeTab(m[2])};
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
  return `/runs/${route.id}/${nextTab}`;
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
