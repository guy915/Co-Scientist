// Class constants owned by the question chooser (chat_questions_panel.tsx)
// that don't belong in chat_setup_classes.ts -- that file is shared with the
// plan/setup document and is edited elsewhere; a chooser-only constant goes
// here instead of alongside its look-alikes there.

// A touch more room between a question's prompt and its first option than
// QUESTION_GROUP_CLASSES's own `gap-[0.6rem]` gives every child of the
// fieldset by default. This sits on the options wrapper alone (a margin, not
// a competing `gap` utility on the same element), so it adds to that gap
// without touching the spacing between the answers themselves, which is
// QUESTION_OPTION_GRID_CLASSES's own `gap`.
export const QUESTION_OPTIONS_TOP_SPACING_CLASSES = 'mt-[0.15rem]';
