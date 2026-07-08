/**
 * Best-effort copy to the system clipboard. Prefers the async Clipboard API
 * and falls back to a hidden textarea + `execCommand` when it is unavailable
 * (insecure or unfocused contexts). Never throws: a failed copy must not
 * abort the caller (e.g. a copy-prompt toast).
 */
export async function copyText(text: string) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return;
    }
    throw new Error('Clipboard API unavailable'); // funnel into the fallback below
  } catch {
    try {
      const textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.setAttribute('readonly', '');
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.append(textarea);
      textarea.select();
      document.execCommand('copy'); // deprecated, but still the most broadly compatible sync fallback
      textarea.remove();
    } catch {
      // Clipboard unavailable; ignore.
    }
  }
}
