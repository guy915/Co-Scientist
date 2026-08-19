// Canonical tab-route table for the goal-report surface. This is the single
// source of truth for the tab segments, their order, their legacy aliases, and
// the ":tab" -> TabName resolution, shared by the run-detail shell (which
// renders the tabs) and the global keyboard shortcuts (which cycle them).

// Canonical tab route segments, in the order the nav bar renders them.
export const TABS = [
  'details',
  'learning',
  'overview',
  'ideas',
  'variants',
] as const;

/** Canonical tab names for the goal-report surface's tab routes. */
export type TabName = (typeof TABS)[number];

// Legacy/alternate route segments that resolve to a canonical TabName, so old
// links (or a stray typo) still land on a real tab instead of 404-ing.
const TAB_ALIASES: Record<string, TabName> = {
  specifications: 'details',
  specs: 'details',
  knowledge: 'learning',
  evidence: 'learning',
  summary: 'overview',
  report: 'overview',
  hypotheses: 'ideas',
  programs: 'variants',
};

/**
 * Resolves the ":tab" route param to a canonical TabName: passes through a
 * recognized tab, maps a known alias, and otherwise falls back to 'details'
 * (covers both a missing param and an unrecognized value).
 */
export function normalizeTab(tab: string | undefined): TabName {
  if (!tab) return 'details';
  if ((TABS as readonly string[]).includes(tab)) return tab as TabName;
  return TAB_ALIASES[tab] ?? 'details';
}

/**
 * Builds a run's tab route. Always via normalizeTab, so a link can never
 * point at an alias (or a typo) that the router would then have to rewrite,
 * and every tab is the same required-param route — switching tabs is a param
 * change, not a remount of RunDetail.
 */
export function tabPath(id: string, tab: string | undefined): string {
  return `/runs/${id}/${normalizeTab(tab)}`;
}

/**
 * The tabs a given run actually shows.
 *
 * "Variants" exists only for a computational-discovery run: on a
 * hypothesis run it would be a permanently empty tab, and an empty tab is
 * indistinguishable from a broken one. Gated on the config key that makes
 * a run a discovery run in the first place, so the nav cannot disagree
 * with what the backend scheduled.
 *
 * @param isDiscovery Whether the run evolves programs rather than ideas.
 * @returns The tabs to render, in nav order.
 */
export function tabsForRun(isDiscovery: boolean): readonly TabName[] {
  return isDiscovery ? TABS : TABS.filter(tab => tab !== 'variants');
}
