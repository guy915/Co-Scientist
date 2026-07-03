import {useEffect, useState} from 'react';
import {Link, useParams} from 'react-router-dom';
import {listDemoRuns} from '@/api/runs';
import {getPublicDemo} from './demo_manifest';
import {NotFoundPage} from './not_found_page';
import {PublicLinkButton} from './public_link_button';
import {Seo} from './seo';

/**
 * Renders a public, SEO-tagged page for a seeded research demo.
 */
export function DemoPage() {
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
          Co-Scientist home
        </Link>

        <header className="demo-header">
          <div>
            <p className="section-label">Completed research demo</p>
            <h1>{demo.title}</h1>
            <p>{demo.summary}</p>
          </div>
          <span className="status-dot">Completed</span>
        </header>

        <section className="demo-goal" aria-labelledby="research-goal-title">
          <h2 id="research-goal-title">Research goal</h2>
          <p>{demo.researchGoal}</p>
        </section>

        <section className="demo-results" aria-labelledby="hypotheses-title">
          <div className="section-heading">
            <h2 id="hypotheses-title">Featured hypotheses</h2>
            <p>
              Illustrative candidates surfaced and ranked by the seeded
              demonstration.
            </p>
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
            <p className="section-label">Evidence and limitations</p>
            <h2 id="evidence-title">A transparent product demonstration.</h2>
          </div>
          <p>{demo.evidenceSummary}</p>
        </section>

        <section className="demo-actions">
          <div>
            <h2>Inspect the full workbench view</h2>
            <p>
              Open the generated ideas, evidence, tournament, and synthesis
              report.
            </p>
          </div>
          <div className="landing-actions">
            {runId ? (
              <PublicLinkButton to={`/runs/${runId}`}>
                Open this demo
              </PublicLinkButton>
            ) : (
              <PublicLinkButton to="/">Open the workbench</PublicLinkButton>
            )}
            <PublicLinkButton to="/" variant="outline">
              Start a new run
            </PublicLinkButton>
          </div>
        </section>
      </article>
    </>
  );
}
