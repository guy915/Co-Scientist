import {fromMarkdown} from 'mdast-util-from-markdown';
import {gfm} from 'micromark-extension-gfm';
import {gfmFromMarkdown} from 'mdast-util-gfm';

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
