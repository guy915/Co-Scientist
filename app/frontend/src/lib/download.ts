/**
 * Triggers a browser file download for arbitrary text content by wrapping it
 * in a Blob, pointing a throwaway anchor at an object URL, and
 * programmatically clicking it. The object URL is revoked immediately after
 * since the download has already been handed off to the browser.
 *
 * The transport is deliberately client-side: the content arrives through an
 * authenticated fetch the caller already made, so the download never needs a
 * direct URL, and therefore never carries auth in a query string.
 *
 * @param filename The download name the browser shows.
 * @param text The file's text content.
 * @param type MIME type of the blob (defaults to Markdown).
 */
export function downloadTextFile(
  filename: string,
  text: string,
  type = 'text/markdown;charset=utf-8',
): void {
  const blob = new Blob([text], {type});
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
