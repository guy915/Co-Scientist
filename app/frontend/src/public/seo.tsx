import {useEffect} from 'react';

interface SeoProps {
  title: string;
  description: string;
  robots?: string; // robots directive, e.g. "noindex, nofollow"
}

/** Updates the named `<meta>` tag in `<head>`, creating it if missing. */
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
  // Runs on mount and whenever any prop changes, mutating document.head
  // directly (this SPA has no <head> manager like react-helmet). Tags are
  // upserted rather than removed on unmount: the next routed page overwrites
  // them with its own values.
  useEffect(() => {
    document.title = title;
    upsertMeta('description', description);
    upsertMeta('robots', robots);
    upsertMeta('googlebot', robots); // Google-specific twin of the robots tag
  }, [description, robots, title]);

  // Head-effect-only component; contributes nothing to the DOM tree.
  return null;
}
