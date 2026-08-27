/**
 * Wire types for the durable research-goal interview (`/api/interviews`).
 *
 * Split out of `run_types.ts` when that file reached its length ceiling:
 * the interview is one coherent surface -- the chat that scopes a goal --
 * and is the only group there that stands on its own. `run_types.ts`
 * re-exports every name here, so import sites are unchanged.
 */

/** The four verified fields derived by the research-goal interview. */
export interface InterviewFields {
  research_challenge: string;
  focus_area: string[];
  preferences: string[];
  title: string | null;
}

/** One clickable answer to an interview question. */
export interface InterviewQuestionOption {
  /** The answer itself, sent verbatim when the scientist picks it. */
  label: string;
  /** One line on what choosing it would mean for the work; may be empty. */
  description: string;
}

/**
 * One multiple-choice question an Agent turn offered.
 *
 * The turn's prose asks the question in full; this is the set of answers
 * the scientist can click instead of writing one out. Typing an answer is
 * always still possible, so a question is an affordance over the turn and
 * never a gate on it.
 */
export interface InterviewQuestion {
  /** Two or three words naming what is being chosen; may be empty. */
  header: string;
  /** The question in full, as the chooser labels it. */
  question: string;
  /** Whether several answers can hold at once. */
  multi_select: boolean;
  options: InterviewQuestionOption[];
}

/** One immutable scientist/Agent interview turn. */
export interface InterviewTurn {
  id: number;
  role: 'user' | 'agent';
  content: string;
  /**
   * The Agent's chain of thought for this turn, when the model produced one.
   * Persisted rather than shown and dropped, so a reopened chat replays the
   * thinking the scientist watched arrive.
   */
  reasoning: string | null;
  /**
   * True when the deterministic fallback authored this Agent turn because no
   * model could be reached (no deployment credential and no bring-your-own
   * key answered it). Per turn, so a mid-session credential change marks
   * only the turns it affects; always false for user turns. The timeline
   * renders a quiet notice on marked turns so scripted questions are never
   * silently passed off as model output.
   */
  fallback: boolean;
  /**
   * The multiple-choice answers this Agent turn offered, if any. Empty for
   * user turns, for turns whose question has no small set of sensible
   * answers, and for every turn recorded before the chooser existed.
   *
   * Per turn and never inherited: only the interview's last Agent turn is
   * still awaiting an answer, so that is the only one the chooser offers.
   */
  questions: InterviewQuestion[];
  created_at: number;
}

/**
 * One entry in the sidebar's chat list: an interview without its transcript,
 * plus the run it started (null until the scientist starts one).
 */
export interface ChatSummary {
  id: string;
  title: string | null;
  challenge: string;
  status: 'active' | 'completed' | 'cancelled';
  run_id: string | null;
  created_at: number;
  updated_at: number;
}

/** Durable interview state returned by the backend. */
export interface Interview {
  id: string;
  client_id: string;
  status: 'active' | 'completed' | 'cancelled';
  fields: InterviewFields;
  current_question: string | null;
  turns: InterviewTurn[];
  /** Documents attached to this chat, which the Agent reads each turn. */
  documents: InterviewDocument[];
  created_at: number;
  updated_at: number;
  completed_at: number | null;
  /**
   * The run this chat started, when it started one. Present on the
   * chat-reopening GET only; a turn frame mid-interview omits it, which is
   * the same thing as "no run yet".
   */
  run_id?: string | null;
}

/** One document attached to a chat, as summarized back to the client. */
export interface InterviewDocument {
  id: string;
  title: string;
  mime_type: string;
  byte_size: number;
}
