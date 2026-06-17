import {useT} from '@/i18n';
import {PublicLinkButton} from './PublicLinkButton';
import {Seo} from './Seo';

/**
 * Renders the 404 page shown for unmatched routes.
 */
export function NotFoundPage() {
  const t = useT();
  return (
    <>
      <Seo
        title={t('landing.notFound.seoTitle')}
        description={t('landing.notFound.seoDescription')}
        path={window.location.pathname}
        robots="noindex, nofollow"
      />
      <section className="not-found-page">
        <p className="section-label">{t('landing.notFound.code')}</p>
        <h1>{t('landing.notFound.title')}</h1>
        <p>{t('landing.notFound.body')}</p>
        <div className="landing-actions">
          <PublicLinkButton to="/">
            {t('landing.notFound.returnHome')}
          </PublicLinkButton>
          <PublicLinkButton to="/runs" variant="outline">
            {t('landing.notFound.openWorkbench')}
          </PublicLinkButton>
        </div>
      </section>
    </>
  );
}
