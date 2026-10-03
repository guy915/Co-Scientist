/**
 * Names of the window-level CustomEvents the workbench uses to talk across
 * React trees (the shell chrome and the routed pages render in separate
 * subtrees, so a window event is the decoupled channel between them).
 * Dispatchers and listeners import the same constant so they can't drift.
 */

/** Detail: the header title string to show ('' clears it). */
export const HEADER_TITLE_EVENT = 'cosci-header-title';

/** Resets the chat workspace to a fresh session. */
export const NEW_CHAT_EVENT = 'cosci-new-chat';

/** A diagnostic log line for the shell's Logs popover. */
export const DIAGNOSTIC_EVENT = 'cosci-diagnostic-event';

/** Signals that the run list changed so run history should reload. */
export const RUNS_CHANGED_EVENT = 'cosci-runs-changed';

/**
 * Signals that the chat list changed so the sidebar should reload: a chat is
 * created by its first turn and gains its run link when one is started, and
 * both happen inside the routed page rather than in the shell.
 */
export const CHATS_CHANGED_EVENT = 'cosci-chats-changed';

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
