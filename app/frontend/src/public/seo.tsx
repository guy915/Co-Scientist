import {useEffect} from 'react';

interface SeoProps {
  title: string;
  description: string;
  robots?: string;
}

function upsertMeta(name: string, content: string) {
  const selector = `meta[name="${name}"]`;
  let element = document.head.querySelector<HTMLMetaElement>(selector);
  if (!element) {
    element = document.createElement('meta');
    element.setAttribute('name', name);
    document.head.appendChild(element);
  }
  element.content = content;
}

/**
 * Syncs the document title and description/robots meta tags for a page.
 *
 * The app has no publicly indexable surface, so callers pass a noindex robots
 * directive and this only maintains the minimal head metadata that needs it.
 *
 * @param props The page title, description, and optional robots directive.
 */
export function Seo({title, description, robots = 'index, follow'}: SeoProps) {
  useEffect(() => {
    document.title = title;
    upsertMeta('description', description);
    upsertMeta('robots', robots);
    upsertMeta('googlebot', robots);
  }, [description, robots, title]);

  return null;
}
