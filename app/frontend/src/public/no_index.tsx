import {Seo} from './seo';

/**
 * Sets page metadata that marks the current route as non-indexable.
 *
 * Convenience wrapper over {@link Seo} with the noindex robots directive and
 * shared branding baked in; workbench pages use this instead of raw Seo.
 *
 * @param props The page title to render in the document head.
 */
export function NoIndex({title}: {title: string}) {
  return (
    <Seo
      title={`${title} - Co-Scientist`}
      description="Co-Scientist research workspace."
      robots="noindex, nofollow"
    />
  );
}
