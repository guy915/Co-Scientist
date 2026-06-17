import {Link} from 'react-router-dom';
import {useT} from '@/i18n';
import {featuredDemo} from './demoManifest';
import {PublicLinkButton} from './PublicLinkButton';
import {Seo} from './Seo';

const landingJsonLd = [
  {
    '@context': 'https://schema.org',
    '@type': 'WebSite',
    name: 'Co-Scientist',
    url: 'https://ai-co-scientist.com/',
    description:
      'An open-source workbench for AI-assisted scientific hypothesis generation.',
  },
  {
    '@context': 'https://schema.org',
    '@type': 'SoftwareApplication',
    name: 'Co-Scientist',
    applicationCategory: 'ScientificApplication',
    operatingSystem: 'Web',
    url: 'https://ai-co-scientist.com/',
    description:
      'A multi-agent research workbench that generates, reviews, ranks, and synthesizes scientific hypotheses.',
    isAccessibleForFree: true,
    codeRepository: 'https://github.com/guy915/Co-Scientist',
  },
];

/**
 * Renders the public marketing landing page with hero, workflow, and demo.
 */
export function LandingPage() {
  const t = useT();
  const workflow = [
    [
      '01',
      t('landing.workflow.scope.title'),
      t('landing.workflow.scope.description'),
    ],
    [
      '02',
      t('landing.workflow.evidence.title'),
      t('landing.workflow.evidence.description'),
    ],
    [
      '03',
      t('landing.workflow.generate.title'),
      t('landing.workflow.generate.description'),
    ],
    [
      '04',
      t('landing.workflow.debate.title'),
      t('landing.workflow.debate.description'),
    ],
    [
      '05',
      t('landing.workflow.synthesize.title'),
      t('landing.workflow.synthesize.description'),
    ],
  ] as const;
  return (
    <>
      <Seo
        title="Co-Scientist"
        description={t('landing.seo.description')}
        path="/"
        jsonLd={landingJsonLd}
      />

      <div className="landing-page">
        <section className="landing-hero" aria-labelledby="landing-title">
          <div className="landing-hero__copy">
            <h1 id="landing-title">{t('app.tagline')}</h1>
            <p>{t('landing.hero.subhead')}</p>
            <div className="landing-actions">
              <PublicLinkButton to="/runs">
                {t('landing.hero.openWorkbench')}
              </PublicLinkButton>
              <PublicLinkButton
                to={`/demos/${featuredDemo.slug}`}
                variant="outline"
              >
                {t('landing.hero.exploreDemo')}
              </PublicLinkButton>
            </div>
          </div>

          <WorkbenchPreview />
        </section>

        <section className="landing-section" aria-labelledby="workflow-title">
          <div className="section-heading">
            <h2 id="workflow-title">{t('landing.workflow.title')}</h2>
            <p>{t('landing.workflow.subtitle')}</p>
          </div>
          <ol className="workflow-strip">
            {workflow.map(([number, title, description]) => (
              <li key={title}>
                <span>{number}</span>
                <div>
                  <h3>{title}</h3>
                  <p>{description}</p>
                </div>
              </li>
            ))}
          </ol>
        </section>

        <section
          className="landing-section featured-demo"
          aria-labelledby="featured-demo-title"
        >
          <div className="featured-demo__intro">
            <p className="section-label">{t('landing.featured.label')}</p>
            <h2 id="featured-demo-title">{featuredDemo.title}</h2>
            <p>{featuredDemo.summary}</p>
            <Link className="inline-link" to={`/demos/${featuredDemo.slug}`}>
              {t('landing.featured.readDemo')}
              <span className="material-symbols-outlined" aria-hidden="true">
                arrow_forward
              </span>
            </Link>
          </div>
          <div className="featured-demo__result">
            <div className="result-meta">
              <span>{t('landing.featured.leadingHypothesis')}</span>
              <span className="status-dot">
                {t('landing.featured.completed')}
              </span>
            </div>
            <h3>{featuredDemo.hypotheses[0].title}</h3>
            <p>{featuredDemo.hypotheses[0].statement}</p>
          </div>
        </section>

        <section
          className="landing-section research-note"
          id="research"
          aria-labelledby="research-title"
        >
          <div>
            <p className="section-label">{t('landing.research.label')}</p>
            <h2 id="research-title">{t('landing.research.title')}</h2>
          </div>
          <div>
            <p>{t('landing.research.body1')}</p>
            <p>{t('landing.research.body2')}</p>
            <a
              className="inline-link"
              href="https://research.google/blog/accelerating-scientific-breakthroughs-with-an-ai-co-scientist/"
              target="_blank"
              rel="noreferrer"
            >
              {t('landing.research.readResearch')}
              <span className="material-symbols-outlined" aria-hidden="true">
                open_in_new
              </span>
            </a>
          </div>
        </section>

        <section className="landing-cta" aria-labelledby="cta-title">
          <div>
            <h2 id="cta-title">{t('landing.cta.title')}</h2>
            <p>{t('landing.cta.subtitle')}</p>
          </div>
          <div className="landing-actions">
            <PublicLinkButton to="/runs/new">
              {t('landing.cta.startRun')}
            </PublicLinkButton>
            <a
              className="public-button public-button--outline"
              href="https://github.com/guy915/Co-Scientist"
              target="_blank"
              rel="noreferrer"
            >
              {t('landing.cta.viewGithub')}
            </a>
          </div>
        </section>
      </div>
    </>
  );
}

function WorkbenchPreview() {
  const t = useT();
  return (
    <section
      className="workbench-preview"
      aria-label={t('landing.hero.previewAria')}
    >
      <div className="preview-header">
        <div>
          <span>{t('landing.preview.researchGoal')}</span>
          <p>{t('landing.preview.goalText')}</p>
        </div>
        <span className="status-dot">{t('landing.preview.completed')}</span>
      </div>
      <div
        className="preview-progress"
        role="progressbar"
        aria-label={t('landing.preview.progressAria')}
        aria-valuemin={0}
        aria-valuemax={5}
        aria-valuenow={5}
      >
        <span />
        <span />
        <span />
        <span />
        <span />
      </div>
      <div className="preview-section-title">
        <span>{t('landing.preview.rankedHypotheses')}</span>
        <span>{t('landing.preview.score')}</span>
      </div>
      <ol className="preview-rankings">
        <li>
          <span className="preview-rank">1</span>
          <div>
            <strong>{t('landing.preview.rank1.title')}</strong>
            <span>{t('landing.preview.rank1.meta')}</span>
          </div>
          <b>1248</b>
        </li>
        <li>
          <span className="preview-rank">2</span>
          <div>
            <strong>{t('landing.preview.rank2.title')}</strong>
            <span>{t('landing.preview.rank2.meta')}</span>
          </div>
          <b>1196</b>
        </li>
        <li className="preview-mobile-hidden">
          <span className="preview-rank">3</span>
          <div>
            <strong>{t('landing.preview.rank3.title')}</strong>
            <span>{t('landing.preview.rank3.meta')}</span>
          </div>
          <b>1164</b>
        </li>
      </ol>
      <div className="preview-footer">
        <span>{t('landing.preview.footer.hypotheses')}</span>
        <span>{t('landing.preview.footer.debates')}</span>
        <span>{t('landing.preview.footer.evidence')}</span>
      </div>
    </section>
  );
}
