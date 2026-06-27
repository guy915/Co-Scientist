import {Seo} from './seo';

/**
 * Sets page metadata that marks the current route as non-indexable.
 *
 * @param props The page title to render in the document head.
 */
export function NoIndex({title}: {title: string}) {
  return (
    <Seo
      title={`${title} - AI Co-Scientist`}
      description="AI Co-Scientist research workspace."
      path={window.location.pathname}
      robots="noindex, nofollow"
    />
  );
}
