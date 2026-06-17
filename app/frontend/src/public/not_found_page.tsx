import {PublicLinkButton} from './public_link_button';
import {Seo} from './seo';

/**
 * Renders the 404 page shown for unmatched routes.
 */
export function NotFoundPage() {
  return (
    <>
      <Seo
        title="Page not found - Co-Scientist"
        description="The page you requested does not exist."
        path={window.location.pathname}
        robots="noindex, nofollow"
      />
      <section className="not-found-page">
        <p className="section-label">404</p>
        <h1>Page not found</h1>
        <p>The page you requested does not exist.</p>
        <div className="landing-actions">
          <PublicLinkButton to="/">Return home</PublicLinkButton>
          <PublicLinkButton to="/runs" variant="outline">
            Open the workbench
          </PublicLinkButton>
        </div>
      </section>
    </>
  );
}
