/**
 * Minimal, dependency-free sanitizer for untrusted HTML fragments.
 *
 * Sources such as PubMed titles and abstracts embed a small set of inline
 * formatting tags (`<i>`, `<sub>`, `<sup>`, ...) that should render as markup
 * rather than as escaped text. The rest of the fragment is untrusted (it flows
 * in from external services), so we escape the entire string first and then
 * re-introduce only the exact, attribute-less tags on the whitelist. Because
 * un-escaping happens after escaping, no attribute, event handler, URL, or
 * disallowed tag can survive: anything not literally `<i>`/`</i>` (etc.) stays
 * escaped and is rendered by the browser as plain text.
 */

const INLINE_TAGS = ['i', 'b', 'em', 'strong', 'sub', 'sup', 'u'] as const;

const ESCAPE_MAP: Record<string, string> = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
};

function escapeHtml(value: string): string {
  return value.replace(/[&<>]/g, char => ESCAPE_MAP[char]);
}

/**
 * Returns an HTML string safe to pass to `dangerouslySetInnerHTML`, preserving
 * only whitelisted inline formatting tags from the input.
 *
 * @param raw The untrusted source fragment.
 * @returns Escaped HTML with whitelisted inline tags reintroduced.
 */
export function renderInlineHtml(raw: string): string {
  let out = escapeHtml(raw);
  for (const tag of INLINE_TAGS) {
    out = out
      .replaceAll(`&lt;${tag}&gt;`, `<${tag}>`)
      .replaceAll(`&lt;/${tag}&gt;`, `</${tag}>`);
  }
  return out;
}
