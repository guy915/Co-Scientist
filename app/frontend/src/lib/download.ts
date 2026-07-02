/**
 * Triggers a browser download of the given href via a transient anchor.
 *
 * @param href The URL (or data URI) to download.
 * @param filename The suggested filename for the downloaded file.
 */
export function triggerDownload(href: string, filename: string): void {
  const a = document.createElement('a');
  a.href = href;
  a.download = filename;
  a.click();
}
