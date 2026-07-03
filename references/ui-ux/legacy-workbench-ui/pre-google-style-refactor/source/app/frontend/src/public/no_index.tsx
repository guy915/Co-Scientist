import {Seo} from './seo';

/**
 * Sets page metadata that marks the current route as non-indexable.
 *
 * @param props The page title to render in the document head.
 */
export function NoIndex({title}: {title: string}) {
  return (
    <Seo
      title={`${title} - Co-Scientist`}
      description="Co-Scientist research workbench."
      path={window.location.pathname}
      robots="noindex, nofollow"
    />
  );
}
