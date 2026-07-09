import {PublicLinkButton} from './public_link_button';
import {Seo} from './seo';

const NOT_FOUND_SECTION_CLASSES =
  'mx-auto min-h-[70vh] w-[min(100%_-_3rem,76rem)] py-[clamp(5rem,12vw,9rem)]';
const NOT_FOUND_EYEBROW_CLASSES =
  'mb-4 text-xs font-semibold tracking-[0.07em] ' +
  'text-[var(--md-sys-color-primary)] uppercase';
const NOT_FOUND_TITLE_CLASSES =
  'm-0 max-w-[12ch] text-[clamp(2.5rem,5.2vw,4rem)] leading-none ' +
  'tracking-normal';
const NOT_FOUND_ACTIONS_CLASSES =
  'mt-8 flex flex-wrap gap-3 max-sm:grid max-sm:grid-cols-1';

/**
 * Renders the 404 page shown for unmatched routes.
 *
 * Mounted on the catch-all `*` route in workbench_app.tsx; marked noindex
 * since error pages should never enter a search index.
 */
export function NotFoundPage() {
  return (
    <>
      <Seo
        title="Page Not Found - Co-Scientist"
        description="The page you requested does not exist."
        robots="noindex, nofollow"
      />
      <section className={NOT_FOUND_SECTION_CLASSES}>
        <p className={NOT_FOUND_EYEBROW_CLASSES}>404</p>
        <h1 className={NOT_FOUND_TITLE_CLASSES}>Page not found</h1>
        <p className="mt-6 max-w-[36rem] text-[1.1rem] text-th-muted-fg">
          The page you requested does not exist.
        </p>
        <div className={NOT_FOUND_ACTIONS_CLASSES}>
          <PublicLinkButton to="/">Return home</PublicLinkButton>
        </div>
      </section>
    </>
  );
}
