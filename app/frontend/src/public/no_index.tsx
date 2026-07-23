import {useEffect} from 'react';

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
 * Sets page metadata that marks the current route as non-indexable.
 *
 * The app has no publicly indexable surface, so every routed page mounts one
 * of these: it syncs the document title (with the shared branding suffix) and
 * writes the description plus the noindex robots directives. Runs on mount
 * and whenever the title changes, mutating document.head directly (this SPA
 * has no <head> manager like react-helmet). Tags are upserted rather than
 * removed on unmount: the next routed page overwrites them with its own
 * values.
 *
 * @param props The page title to render in the document head.
 */
export function NoIndex({title}: {title: string}) {
  useEffect(() => {
    document.title = `${title} - Co-Scientist`;
    upsertMeta('description', 'Co-Scientist research workspace.');
    upsertMeta('robots', 'noindex, nofollow');
    upsertMeta('googlebot', 'noindex, nofollow'); // Google-specific twin
  }, [title]);

  // Head-effect-only component; contributes nothing to the DOM tree.
  return null;
}
