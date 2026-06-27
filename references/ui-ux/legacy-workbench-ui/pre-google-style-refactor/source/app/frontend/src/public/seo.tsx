import {useEffect} from 'react';

const SITE_ORIGIN = 'https://ai-co-scientist.com';
const DEFAULT_IMAGE = `${SITE_ORIGIN}/social-card.jpg`;

interface SeoProps {
  title: string;
  description: string;
  path: string;
  robots?: string;
  image?: string;
  type?: 'website' | 'article';
  jsonLd?: Record<string, unknown> | Record<string, unknown>[];
}

function upsertMeta(
  selector: string,
  attribute: 'name' | 'property',
  key: string,
  content: string,
) {
  let element = document.head.querySelector<HTMLMetaElement>(selector);
  if (!element) {
    element = document.createElement('meta');
    element.setAttribute(attribute, key);
    document.head.appendChild(element);
  }
  element.content = content;
}

/**
 * Syncs document title, meta tags, canonical link, and JSON-LD for a page.
 *
 * @param props The page metadata, robots directive, and optional JSON-LD.
 */
export function Seo({
  title,
  description,
  path,
  robots = 'index, follow',
  image = DEFAULT_IMAGE,
  type = 'website',
  jsonLd,
}: SeoProps) {
  useEffect(() => {
    const canonicalUrl = `${SITE_ORIGIN}${path}`;
    const absoluteImage = image.startsWith('http')
      ? image
      : `${SITE_ORIGIN}${image}`;

    document.title = title;
    upsertMeta('meta[name="description"]', 'name', 'description', description);
    upsertMeta('meta[name="robots"]', 'name', 'robots', robots);
    upsertMeta('meta[name="googlebot"]', 'name', 'googlebot', robots);
    upsertMeta('meta[property="og:type"]', 'property', 'og:type', type);
    upsertMeta('meta[property="og:title"]', 'property', 'og:title', title);
    upsertMeta(
      'meta[property="og:description"]',
      'property',
      'og:description',
      description,
    );
    upsertMeta(
      'meta[property="og:site_name"]',
      'property',
      'og:site_name',
      'Co-Scientist',
    );
    upsertMeta('meta[property="og:url"]', 'property', 'og:url', canonicalUrl);
    upsertMeta(
      'meta[property="og:image"]',
      'property',
      'og:image',
      absoluteImage,
    );
    upsertMeta(
      'meta[name="twitter:card"]',
      'name',
      'twitter:card',
      'summary_large_image',
    );
    upsertMeta('meta[name="twitter:title"]', 'name', 'twitter:title', title);
    upsertMeta(
      'meta[name="twitter:description"]',
      'name',
      'twitter:description',
      description,
    );
    upsertMeta(
      'meta[name="twitter:image"]',
      'name',
      'twitter:image',
      absoluteImage,
    );

    let canonical = document.head.querySelector<HTMLLinkElement>(
      'link[rel="canonical"]',
    );
    if (!canonical) {
      canonical = document.createElement('link');
      canonical.rel = 'canonical';
      document.head.appendChild(canonical);
    }
    canonical.href = canonicalUrl;

    document.head
      .querySelectorAll('script[data-coscientist-jsonld="true"]')
      .forEach(node => {
        node.remove();
      });
    if (jsonLd) {
      const script = document.createElement('script');
      script.type = 'application/ld+json';
      script.dataset.coscientistJsonld = 'true';
      script.textContent = JSON.stringify(jsonLd);
      document.head.appendChild(script);
    }
  }, [description, image, jsonLd, path, robots, title, type]);

  return null;
}
