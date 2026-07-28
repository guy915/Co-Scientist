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
