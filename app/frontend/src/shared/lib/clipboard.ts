// Clipboard APIs may be absent in insecure/unfocused contexts; copying must
// never abort its caller.
export async function copyText(text: string) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return;
    }
    throw new Error('Clipboard API unavailable');
  } catch {
    try {
      const textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.setAttribute('readonly', '');
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.append(textarea);
      textarea.select();
      // Deprecated execCommand remains the broadly compatible synchronous
      // fallback.
      document.execCommand('copy');
      textarea.remove();
    } catch {
      // Clipboard failure must not abort the caller’s action.
    }
  }
}
