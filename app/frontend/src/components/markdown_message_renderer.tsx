import {
  isValidElement,
  memo,
  useEffect,
  useState,
  type ComponentPropsWithoutRef,
  type ReactNode,
} from 'react';
import Markdown from 'react-markdown';
import rehypeHighlight from 'rehype-highlight';
import remarkGfm from 'remark-gfm';
import {Icon} from './icon';
import {copyText} from '../lib/clipboard';
import {fromMarkdown} from 'mdast-util-from-markdown';
import {gfm} from 'micromark-extension-gfm';
import {gfmFromMarkdown} from 'mdast-util-gfm';

// Stable identity across renders: react-markdown treats a fresh array
// literal as a config change and would otherwise be no worse off (memo
// blocks the re-render before it matters), but a shared constant is what a
// later reader expects to see.
const REMARK_PLUGINS = [remarkGfm];

// rehype-highlight operates on the hast tree it is handed (spans with
// `hljs-*` classes), never on a raw-HTML string, so it does not reopen the
// rehype-raw hazard described below. Left at its default `languages: common`
// (37 languages via lowlight) rather than `all` (~190) -- the point of a
// subset, not full coverage, since every language it registers ships in the
// bundle whether a reply ever uses it or not.
const REHYPE_PLUGINS = [rehypeHighlight];

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
  pre: MarkdownPre,
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

/** The fence's language tag (`language-python` -> `python`), or none. */
function fenceLanguage(className: string | undefined): string | null {
  return /language-([\w-]+)/.exec(className ?? '')?.[1] ?? null;
}

/**
 * A fenced block's literal source text, read back out of its highlighted
 * markup. rehype-highlight wraps tokens in nested `<span>`s but never
 * changes the text itself, so concatenating every string leaf reconstructs
 * the original source exactly -- this is what the copy button sends to the
 * clipboard, never the DOM's rendered (and re-selectable, but awkward to
 * grab exactly) text.
 */
function highlightedText(node: ReactNode): string {
  if (typeof node === 'string' || typeof node === 'number') {
    return String(node);
  }
  if (Array.isArray(node)) {
    return node.map(highlightedText).join('');
  }
  if (isValidElement<{children?: ReactNode}>(node)) {
    return highlightedText(node.props.children);
  }
  return '';
}

const COPIED_LABEL_MS = 2_000;

const CODE_COPY_BUTTON_CLASSES =
  'ml-auto grid size-6 shrink-0 cursor-pointer place-items-center ' +
  'rounded-md border-0 bg-transparent p-0 text-cosci-muted ' +
  'hover:bg-cosci-hover hover:text-cosci-fg focus-visible:bg-cosci-hover ' +
  'focus-visible:text-cosci-fg focus-visible:outline-none';

/**
 * Copies `text` on click and flips its own label to "Copied" for
 * {@link COPIED_LABEL_MS}. Routed through the shared `copyText` helper
 * (Clipboard API with an `execCommand` fallback) rather than calling
 * `navigator.clipboard` directly, since that helper already swallows every
 * failure -- a rejected or absent Clipboard API never reaches this
 * component as a thrown error or an unhandled rejection.
 */
function CodeCopyButton({text}: {text: string}) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) {
      return;
    }
    const id = window.setTimeout(() => setCopied(false), COPIED_LABEL_MS);
    return () => window.clearTimeout(id);
  }, [copied]);

  return (
    <button
      type="button"
      className={CODE_COPY_BUTTON_CLASSES}
      aria-label={copied ? 'Copied' : 'Copy code'}
      onClick={() => void copyText(text).then(() => setCopied(true))}
    >
      <Icon
        aria-hidden="true"
        name={copied ? 'check' : 'content_copy'}
        className="text-[1rem]"
      />
    </button>
  );
}

/** The chrome bar above a fenced block: its language (if named) and copy. */
function CodeBlockHeader({
  language,
  text,
}: {
  language: string | null;
  text: string;
}) {
  return (
    <div className="flex items-center gap-2 border-b border-cosci-border px-3 py-1.5 text-xs text-cosci-muted">
      {language && <span className="font-mono">{language}</span>}
      <CodeCopyButton text={text} />
    </div>
  );
}

/**
 * A fenced code block. react-markdown v10 dropped `code`'s `inline` prop, so
 * this owns the block chrome (language label, copy button, the scrolling
 * `pre`) itself rather than have `code` guess whether it is inline from its
 * own props -- `code` above renders unmodified, and stays exclusively an
 * inline-code renderer, because this component reads the fence's `<code>`
 * child by its raw element props (`children` here is that unrendered
 * element -- see `Props<'pre'>`) and re-emits a bare `<code>` from them
 * instead of letting the `code` override run over block code too.
 *
 * The copy button lives in this header, above the scrolling `pre`, so it
 * cannot slide off with the code (`overflow-x-auto` below only wraps the
 * code line, never the header).
 */
function MarkdownPre({children}: Props<'pre'>) {
  const codeElement = isValidElement<{
    className?: string;
    children?: ReactNode;
  }>(children)
    ? children
    : null;
  const {className, children: codeChildren} = codeElement?.props ?? {};
  const language = fenceLanguage(className);

  return (
    <div
      className={`${BLOCK} my-3 overflow-hidden rounded-md border border-cosci-border`}
    >
      <CodeBlockHeader
        language={language}
        text={highlightedText(codeChildren)}
      />
      <pre className="m-0 overflow-x-auto bg-cosci-hover p-3 text-sm">
        <code className={className}>{codeChildren}</code>
      </pre>
    </div>
  );
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
  <Markdown
    remarkPlugins={REMARK_PLUGINS}
    rehypePlugins={REHYPE_PLUGINS}
    components={COMPONENTS}
  >
    {raw}
  </Markdown>
));

/**
 * Renders `content` as markdown.
 *
 * Split into top-level blocks and rendered as one react-markdown instance
 * per block (see splitMarkdownIntoBlocks) rather than one instance for the whole
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
export function MarkdownMessageRenderer({
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

/**
 * Splits a markdown source string into the exact source slice of each
 * top-level block (paragraph, list, table, heading, ...), so each slice can
 * be rendered and memoized independently. Ported from LibreChat's
 * `splitMarkdown.ts` (MIT) and trimmed to what this renderer actually
 * supports: GFM only, no artifact/mermaid/math directives, so no per-block
 * index bookkeeping is needed -- just the raw slices.
 *
 * Only a minimal structural view of the tree is typed here (mirroring the
 * source rather than pulling in `@types/mdast` for one cast) since nothing
 * downstream needs more than type, name, and position.
 */
// `position` is optional only because a hand-built (not string-parsed) mdast
// node could lack one; `mdast-util-from-markdown` always attaches a fully
// resolved `start.offset`/`end.offset` pair when parsing real source text
// (our only caller), so those two are typed as required rather than chased
// through another three levels of optional-chaining.
interface MdastNode {
  type: string;
  children?: MdastNode[];
  position?: {start: {offset: number}; end: {offset: number}};
}

// mdast's Root node always carries a `children` array (possibly empty), so
// this narrower return type -- unlike the recursive `MdastNode` used
// elsewhere -- lets every caller skip an `undefined` check on it.
const parseToMdast = (content: string): {children: MdastNode[]} =>
  fromMarkdown(content, {
    extensions: [gfm()],
    mdastExtensions: [gfmFromMarkdown()],
  }) as {children: MdastNode[]};

/**
 * True if `node` or anything nested inside it (including inside a
 * blockquote or list item) is a reference/footnote definition. Those are
 * document-scoped: a `[ref]` severed from its `[ref]: url` definition by a
 * block split renders as literal text, so a message containing either must
 * render whole.
 */
const containsDefinition = (node: MdastNode): boolean => {
  if (node.type === 'definition' || node.type === 'footnoteDefinition') {
    return true;
  }
  return (node.children ?? []).some(containsDefinition);
};

/**
 * True if any *top-level* child is a raw HTML block. Unlike definitions,
 * this check is intentionally not recursive: `rehype-raw` is not enabled
 * (see markdown_message.tsx), so raw HTML anywhere always escapes to text
 * with no document-scope hazard -- the only splitting hazard is a top-level
 * HTML block, where the separator between two adjacent ones would be lost.
 * Inline HTML inside a paragraph is unaffected by splitting and stays
 * eligible for per-block rendering.
 */
const hasTopLevelHtml = (children: MdastNode[]): boolean =>
  children.some(node => node.type === 'html');

const requiresWholeMessage = (children: MdastNode[]): boolean =>
  hasTopLevelHtml(children) || children.some(containsDefinition);

/** A node's `[start, end)` source offsets, or `undefined` if mdast attached no position. */
function nodeOffsets(node: MdastNode): [number, number] | undefined {
  const position = node.position;
  if (position === undefined) {
    return undefined;
  }
  return [position.start.offset, position.end.offset];
}

/**
 * The exact source slice for every child node, or `undefined` if any node is
 * missing position info -- mdast always attaches one in practice, but a slice
 * this module cannot trust is exactly the case the whole-message fallback
 * exists for.
 */
function sliceBlocks(
  content: string,
  children: MdastNode[],
): string[] | undefined {
  const slices: string[] = [];
  for (const node of children) {
    const offsets = nodeOffsets(node);
    if (offsets === undefined) {
      return undefined;
    }
    slices.push(content.slice(offsets[0], offsets[1]));
  }
  return slices;
}

/**
 * Splits `content` into its top-level block slices. Completed blocks
 * produce byte-identical slices across streamed updates -- that stability is
 * what lets a memoized per-block component skip re-rendering everything but
 * the still-growing final block.
 *
 * Inter-block whitespace (blank lines) is not part of any node's span and is
 * dropped; block-level elements carry their own margins, so rendering each
 * slice independently is visually equivalent to rendering the whole string.
 */
export function splitMarkdownIntoBlocks(content: string): string[] {
  if (!content) {
    return [];
  }

  const children = parseToMdast(content).children;
  if (children.length === 0 || requiresWholeMessage(children)) {
    return [content];
  }

  const slices = sliceBlocks(content, children);
  if (slices === undefined) {
    return [content];
  }
  return slices;
}
