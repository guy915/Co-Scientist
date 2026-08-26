import {
  type Interview,
  type InterviewQuestion,
  type InterviewTurn,
} from '@/api/runs';

/**
 * What the scientist has picked so far, keyed by the question's position in
 * the turn that asked it.
 *
 * Position, not the question's text: the questions of one turn are a fixed
 * list rendered in order, and keying on their wording would break the moment
 * two turns asked the same thing.
 */
export interface QuestionSelections {
  /** Chosen option labels per question, in the order they were clicked. */
  chosen: Record<number, string[]>;
  /** The scientist's own wording per question, when they wrote any. */
  other: Record<number, string>;
}

/** Nothing picked yet. */
export function emptySelections(): QuestionSelections {
  return {chosen: {}, other: {}};
}

// One question's chosen labels after a click. Multi-select accumulates and
// un-picks on a second click; single-select replaces, and a second click on
// the same option clears it -- so a mis-click is always undoable without
// having to dismiss the whole chooser.
function nextChosen(
  current: string[],
  label: string,
  multiSelect: boolean,
): string[] {
  if (current.includes(label)) {
    return current.filter(chosen => chosen !== label);
  }
  return multiSelect ? [...current, label] : [label];
}

/** Returns the selections with one option of one question toggled. */
export function toggleOption(
  selections: QuestionSelections,
  index: number,
  label: string,
  multiSelect: boolean,
): QuestionSelections {
  return {
    ...selections,
    chosen: {
      ...selections.chosen,
      [index]: nextChosen(selections.chosen[index] ?? [], label, multiSelect),
    },
  };
}

/** Returns the selections with one question's free-text answer replaced. */
export function setOther(
  selections: QuestionSelections,
  index: number,
  text: string,
): QuestionSelections {
  return {...selections, other: {...selections.other, [index]: text}};
}

/**
 * Whether one question's "something else" field is open.
 *
 * The key's presence is the flag, not its contents: a scientist who has
 * opened the field but not yet typed into it has still declined every
 * option offered, and the field must stay open while they write.
 */
export function isOtherOpen(
  selections: QuestionSelections,
  index: number,
): boolean {
  return index in selections.other;
}

/** Returns the selections with one question's free-text field toggled. */
export function toggleOther(
  selections: QuestionSelections,
  index: number,
): QuestionSelections {
  if (!isOtherOpen(selections, index)) return setOther(selections, index, '');
  // Rebuilt without the key rather than deleted from a copy: closing the
  // field discards what was written in it, and an entry left behind holding
  // stale text would be sent the next time anything else is answered.
  const other = Object.fromEntries(
    Object.entries(selections.other).filter(([key]) => key !== String(index)),
  );
  return {...selections, other};
}

// Everything the scientist gave for one question: what they clicked, then
// anything they wrote themselves.
function answerParts(selections: QuestionSelections, index: number): string[] {
  const other = (selections.other[index] ?? '').trim();
  const chosen = selections.chosen[index] ?? [];
  return other ? [...chosen, other] : chosen;
}

// One question's answer as the scientist's own turn will read it. The header
// names what is being answered, which is what keeps a turn answering several
// questions unambiguous; a question without one sends the answer bare.
function answerLine(
  question: InterviewQuestion,
  selections: QuestionSelections,
  index: number,
): string {
  const parts = answerParts(selections, index);
  if (!parts.length) return '';
  const answer = parts.join(', ');
  return question.header ? `${question.header}: ${answer}` : answer;
}

/**
 * Composes the scientist's turn from what they picked.
 *
 * The answer is posted as an ordinary interview turn, in plain words, so the
 * Agent reads the conversation it would have read had the scientist typed
 * it -- there is no second channel for a clicked answer, and nothing about
 * the transcript records that the answer was clicked rather than written.
 *
 * @param questions The questions the turn offered, in the order asked.
 * @param selections What the scientist has picked so far.
 * @returns The turn's text, empty when nothing has been picked.
 */
export function answerText(
  questions: InterviewQuestion[],
  selections: QuestionSelections,
): string {
  return questions
    .map((question, index) => answerLine(question, selections, index))
    .filter(Boolean)
    .join('\n');
}

/** The questions of one turn, still awaiting an answer. */
export interface PendingQuestions {
  /** The durable turn that asked them, which keys the chooser's state. */
  turnId: number;
  questions: InterviewQuestion[];
}

/**
 * The questions the scientist can still answer, if any.
 *
 * Exactly one turn is ever pending: the interview's last one, and only when
 * the Agent asked it. Anything earlier has already been answered -- the
 * scientist's reply is the next turn -- and a completed interview has
 * stopped asking, whatever its final turn happened to carry.
 *
 * @param interview The session's interview, or null before there is one.
 * @returns The pending questions, or null when nothing is being asked.
 */
export function pendingQuestions(
  interview: Pick<Interview, 'turns' | 'status'> | null,
): PendingQuestions | null {
  const last = lastPendingTurn(interview);
  if (!last) return null;
  // Read defensively: the store fills `questions` for every turn, including
  // those persisted before it existed, but this is the one field on the
  // payload the composer cannot render without, and reaching into an absent
  // one would take down the whole composer rather than just the chooser.
  const questions = last.questions ?? [];
  return questions.length ? {turnId: last.id, questions} : null;
}

// The turn that could still be awaiting an answer: the last one, when the
// Agent asked it and the interview is still taking answers.
function lastPendingTurn(
  interview: Pick<Interview, 'turns' | 'status'> | null,
): InterviewTurn | null {
  if (!interview || interview.status !== 'active') return null;
  const last = interview.turns.at(-1);
  return last?.role === 'agent' ? last : null;
}
