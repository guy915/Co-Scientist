import {memo, type ComponentPropsWithoutRef, type ReactNode} from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {splitMarkdownIntoBlocks} from './markdown_split';

// Stable identity across renders: react-markdown treats a fresh array
// literal as a config change and would otherwise be no worse off (memo
// blocks the re-render before it matters), but a shared constant is what a
// later reader expects to see.
const REMARK_PLUGINS = [remarkGfm];

/**
 * Renders one assistant message's markdown.
 *
 * The Agent writes ordinary markdown now rather than a line of plain text
 * inside a JSON field, so its replies carry the structure any other
 * assistant's would: emphasis on the term being asked about, a short list
 * when options are laid out, a table when something is compared.
 *
 * This is the only module that imports the markdown renderer, so the choice
 * of renderer stays swappable and every surface showing model prose gets
 * the same typography. Raw HTML in the source is *not* rendered: react-
 * markdown ignores it unless `rehype-raw` is added, and it must not be
 * added here, since this renders untrusted model output.
 *
 * User-authored text is deliberately not routed through this. It is input,
 * not model output, and the request bubble's collapse-past-four-lines
 * measurement depends on its plain text span.
 */

// Vertical rhythm shared by every block-level child. Chat bubbles are read
// in sequence rather than scanned like a document, so blocks sit closer
// together than they would in the Goal Report, and the first and last lose
// their outer margin so a bubble never opens or closes on dead space.
const BLOCK = 'first:mt-0 last:mb-0';

// Pure: the props react-markdown hands a rendered element, minus the ones
// this module overrides. Keyed per tag so each component below stays typed
// against the element it actually renders.
type Props<Tag extends keyof React.JSX.IntrinsicElements> =
  ComponentPropsWithoutRef<Tag>;

/**
 * A link in model prose, which may point anywhere.
 *
 * Opened in a new tab so a citation never navigates the workspace out from
 * under an in-flight chat, and `noopener`/`noreferrer` so the opened page
 * gets neither a handle on this window nor the referrer.
 */
function MarkdownLink({href, children}: Props<'a'>) {
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

/** A table, in its own horizontal scroller so a wide one cannot widen chat. */
function MarkdownTable({children}: Props<'table'>) {
  return (
    <div className={`${BLOCK} my-3 overflow-x-auto`}>
      <table className="w-full border-collapse text-left text-sm">
        {children}
      </table>
    </div>
  );
}

// The element overrides handed to react-markdown. Spacing and type are set
// here rather than through a global prose stylesheet so chat typography
// cannot drift when another surface restyles its own markdown.
const COMPONENTS = {
  a: MarkdownLink,
  table: MarkdownTable,
  p: ({children}: Props<'p'>) => (
    <p className={`${BLOCK} my-2 leading-[1.55]`}>{children}</p>
  ),
  ul: ({children}: Props<'ul'>) => (
    <ul className={`${BLOCK} my-2 list-disc space-y-1 pl-5`}>{children}</ul>
  ),
  ol: ({children}: Props<'ol'>) => (
    <ol className={`${BLOCK} my-2 list-decimal space-y-1 pl-5`}>{children}</ol>
  ),
  li: ({children}: Props<'li'>) => (
    <li className="leading-[1.5]">{children}</li>
  ),
  // Weight only, never a color: emphasis inherits whatever the surface sets,
  // so bold text inside the grey thinking trail stays grey instead of
  // jumping to the reply's foreground and reading as a different voice.
  strong: ({children}: Props<'strong'>) => (
    <strong className="font-medium">{children}</strong>
  ),
  code: ({children}: Props<'code'>) => (
    <code className="rounded-md bg-cosci-hover px-1 py-0.5 font-mono text-[0.9em]">
      {children}
    </code>
  ),
  pre: ({children}: Props<'pre'>) => (
    <pre
      className={`${BLOCK} my-3 overflow-x-auto rounded-md bg-cosci-hover p-3 text-sm`}
    >
      {children}
    </pre>
  ),
  // One heading style for every level: a chat turn is not a document, and
  // an h1 sized like one reads as shouting next to the message before it.
  h1: ({children}: Props<'h1'>) => (
    <MarkdownHeading>{children}</MarkdownHeading>
  ),
  h2: ({children}: Props<'h2'>) => (
    <MarkdownHeading>{children}</MarkdownHeading>
  ),
  h3: ({children}: Props<'h3'>) => (
    <MarkdownHeading>{children}</MarkdownHeading>
  ),
  h4: ({children}: Props<'h4'>) => (
    <MarkdownHeading>{children}</MarkdownHeading>
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
    <blockquote
      className={`${BLOCK} my-2 border-l-2 border-cosci-border pl-3 text-cosci-muted`}
    >
      {children}
    </blockquote>
  ),
  hr: () => <hr className={`${BLOCK} my-3 border-cosci-border`} />,
};

/**
 * A heading in model prose, at one size for every markdown level. Weight
 * only, no color of its own, for the same reason as `strong` above.
 */
function MarkdownHeading({children}: {children: ReactNode}) {
  return <p className={`${BLOCK} mt-3 mb-1.5 font-medium`}>{children}</p>;
}

/**
 * One top-level block's exact source slice, rendered through its own
 * react-markdown instance. Memoized on `raw` (React.memo's default shallow
 * compare, since it is the only prop): a streamed message re-sends every
 * earlier block's slice unchanged on every fragment, so this is what turns
 * repeated whole-message reparsing into "only the growing last block does
 * any work". Keyed by the caller's array index, not by `raw` -- two blocks
 * with identical text (e.g. two blank list items) would otherwise collide.
 */
const MarkdownBlock = memo(({raw}: {raw: string}) => (
  <Markdown remarkPlugins={REMARK_PLUGINS} components={COMPONENTS}>
    {raw}
  </Markdown>
));

/**
 * Renders `content` as markdown.
 *
 * Split into top-level blocks and rendered as one react-markdown instance
 * per block (see markdown_split.ts) rather than one instance for the whole
 * string. A streamed reply grows one fragment at a time, so a single
 * instance reparses the entire source on every fragment; per-block splitting
 * bounds each reparse to the still-growing final block, and memoizes every
 * earlier block against its now-unchanging slice.
 *
 * react-markdown renders its top-level nodes as bare siblings with no
 * wrapping element (that is why this module supplies the outer `div` at
 * all), and `MarkdownBlock` does the same, so splitting does not introduce
 * extra DOM nodes between blocks: the `<p>`, `<ul>`, `<table>`, ... elements
 * from every block still land as direct siblings of that one `div`, in
 * document order. That is what keeps `BLOCK`'s `first:`/`last:` selectors
 * correct after splitting -- they are DOM-tree facts, not React-tree facts,
 * and the DOM tree is unchanged.
 *
 * @param content The message's markdown source.
 * @param className Optional wrapper classes, for the surface's own type size.
 */
export function MarkdownMessage({
  content,
  className = '',
}: {
  content: string;
  className?: string;
}) {
  return (
    // `whitespace-normal` is load-bearing, not tidying: react-markdown emits
    // a literal newline text node between adjacent block elements when a
    // message renders as one instance (the whole-message fallback below, for
    // HTML/definitions), so under pre-wrap every paragraph boundary would
    // paint a full extra line. Per-block splitting sidesteps this for the
    // common case -- each block's own instance has nothing after its single
    // node to leave a trailing newline -- but content isn't known ahead of
    // time to take that path, so the defense stays unconditional. This
    // defends against pre-wrap *inherited* from an ancestor, where an
    // explicit value on this element always wins. It does not defend against
    // a competing whitespace class arriving through `className`, since two
    // classes on one element are resolved by stylesheet order -- so the
    // surface passing the class stays responsible for not sending one
    // (see MODEL_BUBBLE_TEXT_CLASSES).
    //
    // A markdown list written with blank lines between its items is "loose",
    // and every item's content is then wrapped in a paragraph. Those inherit
    // the paragraph margin above, which double-spaces the list and reads as
    // broken rather than as emphasis -- so a paragraph inside a list item
    // carries no vertical margin of its own.
    <div
      className={`min-w-0 break-words whitespace-normal [&_li_p]:my-0 ${className}`}
    >
      {splitMarkdownIntoBlocks(content).map((raw, index) => (
        // Keyed by position, not by `raw`: streaming only ever appends to
        // the final block, so every earlier index stays stable, and keying
        // by text would collide two blocks with identical content (e.g. two
        // blank list items).
        <MarkdownBlock key={index} raw={raw} />
      ))}
    </div>
  );
}
