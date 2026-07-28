/**
 * Whether a click asked the browser for something other than plain
 * navigation: a new tab/window, a download, or a background open.
 *
 * A link whose handler also mutates this tab's state has to check this. The
 * browser handles a modified click by opening the target elsewhere and
 * leaving this page alone -- but the React handler still runs, so without
 * this guard "New chat" in a new tab would also wipe the conversation in the
 * tab the user is still reading.
 *
 * @param event The click event from the anchor.
 * @returns True when the browser will not navigate this tab.
 */
export function isModifiedClick(event: {
  metaKey: boolean;
  ctrlKey: boolean;
  shiftKey: boolean;
  altKey: boolean;
  button: number;
}): boolean {
  if (event.button !== 0) return true;
  return event.metaKey || event.ctrlKey || event.shiftKey || event.altKey;
}
