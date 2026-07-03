import {PublicLinkButton} from './public_link_button';
import {Seo} from './seo';

/**
 * Renders the 404 page shown for unmatched routes.
 */
export function NotFoundPage() {
  return (
    <>
      <Seo
        title="Page not found - AI Co-Scientist"
        description="The page you requested does not exist."
        path={window.location.pathname}
        robots="noindex, nofollow"
      />
      <section className="mx-auto min-h-[70vh] w-[min(100%_-_3rem,76rem)] py-[clamp(5rem,12vw,9rem)]">
        <p className="mb-4 text-xs font-semibold tracking-[0.07em] text-[var(--md-sys-color-primary)] uppercase">
          404
        </p>
        <h1 className="m-0 max-w-[12ch] text-[clamp(2.5rem,5.2vw,4rem)] leading-none tracking-normal">
          Page not found
        </h1>
        <p className="mt-6 max-w-[36rem] text-[1.1rem] text-th-muted-fg">
          The page you requested does not exist.
        </p>
        <div className="mt-8 flex flex-wrap gap-3 max-sm:grid max-sm:grid-cols-1">
          <PublicLinkButton to="/">Return home</PublicLinkButton>
        </div>
      </section>
    </>
  );
}
