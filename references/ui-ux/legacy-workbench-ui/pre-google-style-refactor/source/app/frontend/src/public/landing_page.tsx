import {Link} from 'react-router-dom';
import {featuredDemo} from './demo_manifest';
import {PublicLinkButton} from './public_link_button';
import {Seo} from './seo';

const workflow = [
  ['01', 'Scope', 'Clarify the research goal and plan the investigation.'],
  ['02', 'Evidence', 'Retrieve literature and inspect supporting context.'],
  ['03', 'Generate', 'Produce distinct, testable candidate hypotheses.'],
  [
    '04',
    'Debate',
    'Review, compare, and rank ideas through pairwise critique.',
  ],
  [
    '05',
    'Synthesize',
    'Assemble the strongest reasoning into a research report.',
  ],
] as const;

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
  return (
    <>
      <Seo
        title="Co-Scientist"
        description="An AI-powered assistant for scientific discovery. Generates hypotheses, debates approaches, and proposes solutions – grounded in literature."
        path="/about"
        jsonLd={landingJsonLd}
      />

      <div className="landing-page">
        <section className="landing-hero" aria-labelledby="landing-title">
          <div className="landing-hero__copy">
            <h1 id="landing-title">
              Turn research questions into testable hypotheses.
            </h1>
            <p>
              Accelerating scientific discovery with AI-driven collaboration.
            </p>
            <div className="landing-actions">
              <PublicLinkButton to="/">Open the workbench</PublicLinkButton>
              <PublicLinkButton
                to={`/demos/${featuredDemo.slug}`}
                variant="outline"
              >
                Explore a demo
              </PublicLinkButton>
            </div>
          </div>

          <WorkbenchPreview />
        </section>

        <section className="landing-section" aria-labelledby="workflow-title">
          <div className="section-heading">
            <h2 id="workflow-title">From question to research direction</h2>
            <p>
              A structured multi-agent workflow keeps the reasoning inspectable
              at every stage.
            </p>
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
            <p className="section-label">Completed research demo</p>
            <h2 id="featured-demo-title">{featuredDemo.title}</h2>
            <p>{featuredDemo.summary}</p>
            <Link className="inline-link" to={`/demos/${featuredDemo.slug}`}>
              Read the completed demo
              <span className="material-symbols-outlined" aria-hidden="true">
                arrow_forward
              </span>
            </Link>
          </div>
          <div className="featured-demo__result">
            <div className="result-meta">
              <span>Leading hypothesis</span>
              <span className="status-dot">Completed</span>
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
            <p className="section-label">Built from published research</p>
            <h2 id="research-title">
              An open implementation of a multi-agent research workflow.
            </h2>
          </div>
          <div>
            <p>
              Co-Scientist is an independent open-source implementation inspired
              by published Google DeepMind research on AI co-scientist systems.
            </p>
            <p>
              This project is not affiliated with, endorsed by, or an official
              product of Google or Google DeepMind.
            </p>
            <a
              className="inline-link"
              href="https://research.google/blog/accelerating-scientific-breakthroughs-with-an-ai-co-scientist/"
              target="_blank"
              rel="noreferrer"
            >
              Read the published research
              <span className="material-symbols-outlined" aria-hidden="true">
                open_in_new
              </span>
            </a>
          </div>
        </section>

        <section className="landing-cta" aria-labelledby="cta-title">
          <div>
            <h2 id="cta-title">Start with a research question.</h2>
            <p>Generate, challenge, and refine hypotheses in the workbench.</p>
          </div>
          <div className="landing-actions">
            <PublicLinkButton to="/">Start a research run</PublicLinkButton>
            <a
              className="public-button public-button--outline"
              href="https://github.com/guy915/Co-Scientist"
              target="_blank"
              rel="noreferrer"
            >
              View on GitHub
            </a>
          </div>
        </section>
      </div>
    </>
  );
}

function WorkbenchPreview() {
  return (
    <section
      className="workbench-preview"
      aria-label="Example Co-Scientist workbench result"
    >
      <div className="preview-header">
        <div>
          <span>Research goal</span>
          <p>How could ferroptosis modulation improve chemotherapy response?</p>
        </div>
        <span className="status-dot">Completed</span>
      </div>
      <div
        className="preview-progress"
        role="progressbar"
        aria-label="Research workflow progress"
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
        <span>Ranked hypotheses</span>
        <span>Score</span>
      </div>
      <ol className="preview-rankings">
        <li>
          <span className="preview-rank">1</span>
          <div>
            <strong>Coordinate redox and lipid-peroxidation control</strong>
            <span>High testability · 4 evidence links</span>
          </div>
          <b>1248</b>
        </li>
        <li>
          <span className="preview-rank">2</span>
          <div>
            <strong>Target a rate-limiting metabolic dependency</strong>
            <span>High novelty · 3 evidence links</span>
          </div>
          <b>1196</b>
        </li>
        <li className="preview-mobile-hidden">
          <span className="preview-rank">3</span>
          <div>
            <strong>Sequence sensitization before chemotherapy</strong>
            <span>Moderate evidence · 3 evidence links</span>
          </div>
          <b>1164</b>
        </li>
      </ol>
      <div className="preview-footer">
        <span>10 hypotheses</span>
        <span>12 debates</span>
        <span>4 evidence records</span>
      </div>
    </section>
  );
}
