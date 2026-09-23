/**
 * The detail pane's jump-to-section rail and the section vocabulary it and
 * the pane both build from.
 *
 * Split out of `ideas_detail_pane.tsx` to keep that module within the repo's
 * 500-line ceiling. The section titles live here rather than in the pane
 * because both sides need them and a second copy is how a rail link and its
 * heading drift apart.
 */
import {type MouseEvent} from 'react';
import {smoothScrollToSection} from '@/lib/smooth_scroll';

const IDEA_SECTIONS_RAIL_CLASSES =
  'idea-sections-rail m-5 min-w-0 min-w-[12.5rem] self-start ' +
  // Stacked, the rail is beside nothing and just pushes the detail down.
  'rounded-[10px] bg-cosci-panel p-5 max-[1023px]:hidden';

const IDEA_SECTIONS_LABEL_CLASSES =
  'text-[0.9rem] tracking-[0.1px] text-cosci-idea-title-text';

// Reference: ul with 20px above the first link, then li+li margin-top 24px.
const IDEA_SECTIONS_LIST_CLASSES = 'mt-5 grid gap-6';

// Slightly smaller than the body so the longest link ("Tournament
// performance >") fits on one line without widening the rail.
const IDEA_SECTION_LINK_CLASSES =
  'block whitespace-nowrap text-[0.85rem] leading-6 font-medium ' +
  'text-cosci-blue no-underline';

// The scroll pane a rail jump targets: the detail pane itself (which scrolls
// once the columns stack, below 1024px) or its `.cosci-report-scroll`
// ancestor (the desktop scroller, owned by run_detail.tsx), so the
// smooth-scroll lib carries no app-specific class knowledge.
const IDEA_SCROLL_PANE_SELECTOR = '.idea-detail-pane, .cosci-report-scroll';

// Detail section titles, in render order. Single source of truth so the
// section headings and the rail links can't drift apart.
export const SECTIONS = {
  overview: 'Hypothesis overview',
  description: 'Description',
  provenance: 'Provenance & lineage',
  outcomes: 'Empirical outcomes',
  reviewSummary: 'Review summary',
  reviewCritiques: 'Review critiques',
  tournament: 'Tournament performance',
  matchSummary: 'Match summary',
} as const;

// The rail links every section except "Match summary" (shown inline only).
const RAIL_SECTIONS: readonly string[] = [
  SECTIONS.overview,
  SECTIONS.description,
  SECTIONS.provenance,
  SECTIONS.outcomes,
  SECTIONS.reviewSummary,
  SECTIONS.reviewCritiques,
  SECTIONS.tournament,
];

/**
 * Anchor id for a detail section, shared by the section and its rail link.
 *
 * @param title The section's visible heading.
 * @returns The slug used as both the section id and the link's hash.
 */
export function sectionSlug(title: string): string {
  return title.toLowerCase().replaceAll(' ', '-');
}

// Intercepts a rail-link click to smooth-scroll to its section (with a 16px
// offset) instead of the browser's default instant-jump anchor navigation.
// Falls through to the default behavior when the target isn't found.
function smoothSectionClick(
  event: MouseEvent<HTMLAnchorElement>,
  sectionId: string,
) {
  const didScroll = smoothScrollToSection(
    sectionId,
    16,
    IDEA_SCROLL_PANE_SELECTOR,
  );
  if (!didScroll) return;
  event.preventDefault();
}

/**
 * Right-hand jump-to-section links (hidden once the columns stack, see
 * IDEA_SECTIONS_RAIL_CLASSES). Built from RAIL_SECTIONS, so it always
 * mirrors the actual section ids without being kept in sync by hand.
 */
export function SectionsRail() {
  return (
    <aside className={IDEA_SECTIONS_RAIL_CLASSES} aria-label="Sections">
      <span className={IDEA_SECTIONS_LABEL_CLASSES}>Sections</span>
      <nav className={IDEA_SECTIONS_LIST_CLASSES}>
        {RAIL_SECTIONS.map(item => (
          <a
            key={item}
            href={`#${sectionSlug(item)}`}
            className={IDEA_SECTION_LINK_CLASSES}
            onClick={event => smoothSectionClick(event, sectionSlug(item))}
          >
            {item} &gt;
          </a>
        ))}
      </nav>
    </aside>
  );
}
