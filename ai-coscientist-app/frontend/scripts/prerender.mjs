import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const dist = path.join(root, "dist");
const baseHtml = await readFile(path.join(dist, "index.html"), "utf8");
const origin = "https://ai-co-scientist.com";

const routes = [
  {
    path: "/",
    title: "Co-Scientist",
    description:
      "An AI-powered assistant for scientific discovery. Generates hypotheses, debates approaches, and proposes solutions — grounded in literature.",
    heading: "Turn research questions into testable hypotheses.",
    body: "Accelerating scientific discovery with AI-driven collaboration.",
    jsonLd: [
      {
        "@context": "https://schema.org",
        "@type": "WebSite",
        name: "Co-Scientist",
        url: "https://ai-co-scientist.com/",
        description: "An open-source workbench for AI-assisted scientific hypothesis generation.",
      },
      {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        name: "Co-Scientist",
        applicationCategory: "ScientificApplication",
        operatingSystem: "Web",
        url: "https://ai-co-scientist.com/",
        description:
          "A multi-agent research workbench that generates, reviews, ranks, and synthesizes scientific hypotheses.",
        isAccessibleForFree: true,
        codeRepository: "https://github.com/guy915/Co-Scientist",
      },
    ],
  },
  {
    path: "/demos/ferroptosis-pancreatic-cancer",
    title: "Ferroptosis in Pancreatic Cancer Demo - Co-Scientist",
    description:
      "Explore a completed Co-Scientist demonstration on ferroptosis regulation and chemotherapy sensitivity in pancreatic cancer.",
    heading: "Ferroptosis in pancreatic cancer",
    body: "A completed demonstration exploring regulatory checkpoints that may connect ferroptosis sensitivity with chemotherapy response.",
    jsonLd: {
      "@context": "https://schema.org",
      "@type": "Article",
      headline: "Ferroptosis in pancreatic cancer",
      description:
        "A completed demonstration exploring regulatory checkpoints that may connect ferroptosis sensitivity with chemotherapy response.",
      mainEntityOfPage: "https://ai-co-scientist.com/demos/ferroptosis-pancreatic-cancer",
      author: {
        "@type": "Organization",
        name: "Co-Scientist",
        url: "https://ai-co-scientist.com/",
      },
      isPartOf: {
        "@type": "WebSite",
        name: "Co-Scientist",
        url: "https://ai-co-scientist.com/",
      },
    },
  },
  {
    path: "/demos/synaptic-pruning-cognitive-flexibility",
    title: "Synaptic Pruning and Cognitive Flexibility Demo - Co-Scientist",
    description:
      "Explore a completed Co-Scientist demonstration on adolescent synaptic pruning and cognitive flexibility.",
    heading: "Synaptic pruning and cognitive flexibility",
    body: "A completed demonstration examining how developmental timing, circuit refinement, and regulatory feedback could influence cognitive flexibility.",
    jsonLd: {
      "@context": "https://schema.org",
      "@type": "Article",
      headline: "Synaptic pruning and cognitive flexibility",
      description:
        "A completed demonstration examining how developmental timing, circuit refinement, and regulatory feedback could influence cognitive flexibility.",
      mainEntityOfPage: "https://ai-co-scientist.com/demos/synaptic-pruning-cognitive-flexibility",
      author: {
        "@type": "Organization",
        name: "Co-Scientist",
        url: "https://ai-co-scientist.com/",
      },
      isPartOf: {
        "@type": "WebSite",
        name: "Co-Scientist",
        url: "https://ai-co-scientist.com/",
      },
    },
  },
  {
    path: "/demos/biofilm-antibiotic-resistance",
    title: "Biofilm Antibiotic Resistance Demo - Co-Scientist",
    description:
      "Explore a completed Co-Scientist demonstration on metabolic pathways and antibiotic resistance in Staphylococcus aureus biofilms.",
    heading: "Biofilm antibiotic resistance",
    body: "A completed demonstration investigating metabolic and regulatory mechanisms that may sustain antibiotic tolerance in biofilms.",
    jsonLd: {
      "@context": "https://schema.org",
      "@type": "Article",
      headline: "Biofilm antibiotic resistance",
      description:
        "A completed demonstration investigating metabolic and regulatory mechanisms that may sustain antibiotic tolerance in biofilms.",
      mainEntityOfPage: "https://ai-co-scientist.com/demos/biofilm-antibiotic-resistance",
      author: {
        "@type": "Organization",
        name: "Co-Scientist",
        url: "https://ai-co-scientist.com/",
      },
      isPartOf: {
        "@type": "WebSite",
        name: "Co-Scientist",
        url: "https://ai-co-scientist.com/",
      },
    },
  },
];

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function renderRoute(route) {
  const canonical = `${origin}${route.path}`;
  const jsonLd = JSON.stringify(route.jsonLd).replaceAll("</", "<\\/");
  return baseHtml
    .replace(/<title>.*?<\/title>/, `<title>${escapeHtml(route.title)}</title>`)
    .replace(
      /<meta name="description" content=".*?" \/>/,
      `<meta name="description" content="${escapeHtml(route.description)}" />`
    )
    .replace(/<link rel="canonical" href=".*?" \/>/, `<link rel="canonical" href="${canonical}" />`)
    .replace(
      /<meta property="og:title" content=".*?" \/>/,
      `<meta property="og:title" content="${escapeHtml(route.title)}" />`
    )
    .replace(
      /<meta property="og:description" content=".*?" \/>/,
      `<meta property="og:description" content="${escapeHtml(route.description)}" />`
    )
    .replace(
      /<meta property="og:url" content=".*?" \/>/,
      `<meta property="og:url" content="${canonical}" />`
    )
    .replace(
      /<meta name="twitter:title" content=".*?" \/>/,
      `<meta name="twitter:title" content="${escapeHtml(route.title)}" />`
    )
    .replace(
      /<meta name="twitter:description" content=".*?" \/>/,
      `<meta name="twitter:description" content="${escapeHtml(route.description)}" />`
    )
    .replace(
      /<noscript>[\s\S]*?<\/noscript>/,
      `<noscript><main><h1>${escapeHtml(route.heading)}</h1><p>${escapeHtml(route.body)}</p></main></noscript>`
    )
    .replace("</head>", `<script type="application/ld+json">${jsonLd}</script></head>`);
}

for (const route of routes) {
  const outputDirectory =
    route.path === "/" ? dist : path.join(dist, route.path.replace(/^\//, ""));
  await mkdir(outputDirectory, { recursive: true });
  await writeFile(path.join(outputDirectory, "index.html"), renderRoute(route));
}

const notFoundHtml = baseHtml
  .replace(/<title>.*?<\/title>/, "<title>Page not found - Co-Scientist</title>")
  .replace(
    /<meta name="description" content=".*?" \/>/,
    '<meta name="description" content="The page you requested does not exist." />'
  )
  .replace(
    /<meta name="robots" content=".*?" \/>/,
    '<meta name="robots" content="noindex, nofollow" />'
  )
  .replace(
    /<meta name="googlebot" content=".*?" \/>/,
    '<meta name="googlebot" content="noindex, nofollow" />'
  )
  .replace(
    /<meta property="og:title" content=".*?" \/>/,
    '<meta property="og:title" content="Page not found - Co-Scientist" />'
  )
  .replace(
    /<meta property="og:description" content=".*?" \/>/,
    '<meta property="og:description" content="The page you requested does not exist." />'
  )
  .replace(
    /<meta name="twitter:title" content=".*?" \/>/,
    '<meta name="twitter:title" content="Page not found - Co-Scientist" />'
  )
  .replace(
    /<meta name="twitter:description" content=".*?" \/>/,
    '<meta name="twitter:description" content="The page you requested does not exist." />'
  )
  .replace(/<link rel="canonical" href=".*?" \/>/, "")
  .replace(/<meta property="og:url" content=".*?" \/>/, "")
  .replace(
    /<noscript>[\s\S]*?<\/noscript>/,
    '<noscript><main><h1>Page not found</h1><p>The page you requested does not exist.</p><p><a href="/">Return home</a> · <a href="/runs">Open the workbench</a></p></main></noscript>'
  );

await writeFile(path.join(dist, "404.html"), notFoundHtml);

console.log(`Pre-rendered ${routes.length} public routes and 404.html.`);
