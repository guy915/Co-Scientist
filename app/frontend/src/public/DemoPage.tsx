import {useEffect, useState} from 'react';
import {Link, useParams} from 'react-router-dom';
import {listDemoRuns} from '@/api/runs';
import {useT} from '@/i18n';
import {getPublicDemo} from './demoManifest';
import {NotFoundPage} from './NotFoundPage';
import {PublicLinkButton} from './PublicLinkButton';
import {Seo} from './Seo';

/**
 * Renders a public, SEO-tagged page for a seeded research demo.
 */
export function DemoPage() {
  const t = useT();
  const {slug} = useParams<{slug: string}>();
  const demo = getPublicDemo(slug);
  const [runId, setRunId] = useState<string | null>(null);

  useEffect(() => {
    if (!demo) return;
    let cancelled = false;
    void listDemoRuns()
      .then(runs => {
        const matchingRun = runs.find(
          run => run.research_goal === demo.relatedRunGoal,
        );
        if (!cancelled) setRunId(matchingRun?.id ?? null);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [demo]);

  if (!demo) return <NotFoundPage />;

  const canonicalPath = `/demos/${demo.slug}`;
  const jsonLd = {
    '@context': 'https://schema.org',
    '@type': 'Article',
    headline: demo.title,
    description: demo.summary,
    mainEntityOfPage: `https://ai-co-scientist.com${canonicalPath}`,
    author: {
      '@type': 'Organization',
      name: 'Co-Scientist',
      url: 'https://ai-co-scientist.com/',
    },
    isPartOf: {
      '@type': 'WebSite',
      name: 'Co-Scientist',
      url: 'https://ai-co-scientist.com/',
    },
  };

  return (
    <>
      <Seo
        title={demo.pageTitle}
        description={demo.pageDescription}
        path={canonicalPath}
        image={demo.socialImage}
        type="article"
        jsonLd={jsonLd}
      />
      <article className="demo-page">
        <Link className="demo-back-link" to="/">
          <span className="material-symbols-outlined" aria-hidden="true">
            arrow_back
          </span>
          {t('landing.demo.backLink')}
        </Link>

        <header className="demo-header">
          <div>
            <p className="section-label">{t('landing.demo.label')}</p>
            <h1>{demo.title}</h1>
            <p>{demo.summary}</p>
          </div>
          <span className="status-dot">{t('landing.demo.completed')}</span>
        </header>

        <section className="demo-goal" aria-labelledby="research-goal-title">
          <h2 id="research-goal-title">{t('landing.demo.researchGoal')}</h2>
          <p>{demo.researchGoal}</p>
        </section>

        <section className="demo-results" aria-labelledby="hypotheses-title">
          <div className="section-heading">
            <h2 id="hypotheses-title">
              {t('landing.demo.featuredHypotheses')}
            </h2>
            <p>{t('landing.demo.featuredSubtitle')}</p>
          </div>
          <ol>
            {demo.hypotheses.map((hypothesis, index) => (
              <li key={hypothesis.title}>
                <span>{String(index + 1).padStart(2, '0')}</span>
                <div>
                  <h3>{hypothesis.title}</h3>
                  <p>{hypothesis.statement}</p>
                </div>
              </li>
            ))}
          </ol>
        </section>

        <section className="demo-evidence" aria-labelledby="evidence-title">
          <div>
            <p className="section-label">{t('landing.demo.evidenceLabel')}</p>
            <h2 id="evidence-title">{t('landing.demo.evidenceTitle')}</h2>
          </div>
          <p>{demo.evidenceSummary}</p>
        </section>

        <section className="demo-actions">
          <div>
            <h2>{t('landing.demo.inspectTitle')}</h2>
            <p>{t('landing.demo.inspectSubtitle')}</p>
          </div>
          <div className="landing-actions">
            {runId ? (
              <PublicLinkButton to={`/runs/${runId}`}>
                {t('landing.demo.openThisDemo')}
              </PublicLinkButton>
            ) : (
              <PublicLinkButton to="/runs">
                {t('landing.demo.openWorkbench')}
              </PublicLinkButton>
            )}
            <PublicLinkButton to="/runs/new" variant="outline">
              {t('landing.demo.startNewRun')}
            </PublicLinkButton>
          </div>
        </section>
      </article>
    </>
  );
}
