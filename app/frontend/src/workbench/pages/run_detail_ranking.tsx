import {type ComponentPropsWithoutRef} from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {type Report} from '@/api/runs';
import {
  REPORT_DOCUMENT_CLASSES,
  REPORT_H2_CLASSES,
  REPORT_H3_CLASSES,
  REPORT_H4_CLASSES,
  REPORT_LIST_CLASSES,
} from './run_detail_document';

/**
 * Top Ranking Hypotheses tab (R14-11): renders the second of a run's two
 * report documents as markdown.
 *
 * A second react-markdown call site, alongside `components/markdown_message
 * .tsx` (chat replies): that module's own heading style is deliberately
 * uniform ("an h1 sized like one reads as shouting next to the message
 * before it" -- see its docstring), which is right for a short chat turn
 * and wrong for this multi-section document, where h1 through h4 carry
 * real structural meaning readers scan by. Reusing `run_detail_document
 * .tsx`'s own heading classes here keeps this tab's typography matching
 * every other report tab's, even though the source markup and renderer
 * differ from theirs (a raw document string vs. structured JSON payload
 * fields).
 */

const REMARK_PLUGINS = [remarkGfm];

type Props<Tag extends keyof React.JSX.IntrinsicElements> =
  ComponentPropsWithoutRef<Tag>;

/** A link in the document, opened in a new tab like any other citation. */
function DocumentLink({href, children}: Props<'a'>) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-cosci-blue underline underline-offset-2"
    >
      {children}
    </a>
  );
}

/** A table, in its own horizontal scroller so a wide one cannot widen the page. */
function DocumentTable({children}: Props<'table'>) {
  return (
    <div className="my-4 overflow-x-auto">
      <table className="w-full border-collapse text-left text-sm">
        {children}
      </table>
    </div>
  );
}

// The comparison tables (Idea Comparison, Existing Solutions) render as
// nested bullet lists (see report_markdown_meta_review.py), not markdown
// tables -- this override exists for any future section that does emit a
// real ``|`` table, and for GFM tables a hand-edited report might carry.
const COMPONENTS = {
  a: DocumentLink,
  table: DocumentTable,
  h1: ({children}: Props<'h1'>) => (
    <h2 className={REPORT_H2_CLASSES}>{children}</h2>
  ),
  h2: ({children}: Props<'h2'>) => (
    <h3 className={REPORT_H3_CLASSES}>{children}</h3>
  ),
  h3: ({children}: Props<'h3'>) => (
    <h4 className={REPORT_H4_CLASSES}>{children}</h4>
  ),
  h4: ({children}: Props<'h4'>) => (
    <h4 className={REPORT_H4_CLASSES}>{children}</h4>
  ),
  p: ({children}: Props<'p'>) => (
    <p className="my-3 leading-[1.6]">{children}</p>
  ),
  ul: ({children}: Props<'ul'>) => (
    <ul className={REPORT_LIST_CLASSES}>{children}</ul>
  ),
  ol: ({children}: Props<'ol'>) => (
    <ol className={`${REPORT_LIST_CLASSES} list-decimal`}>{children}</ol>
  ),
  li: ({children}: Props<'li'>) => (
    <li className="my-1 leading-[1.55]">{children}</li>
  ),
  strong: ({children}: Props<'strong'>) => (
    <strong className="font-medium">{children}</strong>
  ),
  th: ({children}: Props<'th'>) => (
    <th className="border-b border-cosci-border px-2 py-1.5 font-medium">
      {children}
    </th>
  ),
  td: ({children}: Props<'td'>) => (
    <td className="border-b border-cosci-border px-2 py-1.5 align-top">
      {children}
    </td>
  ),
  blockquote: ({children}: Props<'blockquote'>) => (
    <blockquote className="my-3 border-l-2 border-cosci-border pl-3 text-cosci-muted">
      {children}
    </blockquote>
  ),
  hr: () => <hr className="my-6 border-cosci-border" />,
};

const EMPTY_STATE_CLASSES = 'py-12 text-center text-cosci-muted';

/**
 * The Top Ranking Hypotheses tab body.
 *
 * `report.markdown_text_ranking` is null/absent on a run whose report
 * predates the R14-11 split -- this tab is not shown in the nav strip for
 * such a run (see `visibleTabs` in run_detail.tsx), but the route still
 * resolves directly (a stale bookmark, a typed URL), so this renders a
 * plain explanation rather than a blank page.
 */
export function RankingDocumentView({report}: {report: Report | null}) {
  const markdown = report?.markdown_text_ranking;
  if (!markdown) {
    return (
      <article className={REPORT_DOCUMENT_CLASSES}>
        <p className={EMPTY_STATE_CLASSES}>
          This run has no Top Ranking Hypotheses document. Older runs published
          a single combined report -- see the Research Overview tab instead.
        </p>
      </article>
    );
  }
  return (
    <article className={REPORT_DOCUMENT_CLASSES}>
      <Markdown remarkPlugins={REMARK_PLUGINS} components={COMPONENTS}>
        {markdown}
      </Markdown>
    </article>
  );
}
