import {type Interview, type InterviewTurn} from '@/api/runs';
import {interviewToRunSpec} from '../run_spec';
import {type ChatEntry} from '../pages/chat_timeline_cards';
import {type HandlerDeps} from './chat_session_types';

/**
 * One persisted turn as a timeline bubble.
 *
 * The Agent's reasoning rides along so a turn shows the thinking that
 * produced it exactly as it did while streaming, and the durable turn id
 * rides along so the bubble can be edited or retried in place.
 */
export function turnToEntry(turn: InterviewTurn): ChatEntry {
  const role = turn.role === 'agent' ? 'assistant' : 'user';
  return {
    // Keyed by the turn, not freshly generated: the log is rebuilt from the
    // server after every turn, and a new id each time would remount every
    // bubble on the page (losing its measured collapse state) to redraw text
    // that did not change.
    id: `turn-${turn.id}`,
    role,
    content: turn.content,
    reasoning: turn.reasoning ?? undefined,
    turnId: turn.id,
    created_at: turn.created_at,
  };
}

/**
 * Splits an interview's transcript for display: a completed interview's
 * closing Agent turn becomes the plan card's lead-in rather than a bubble of
 * its own, so the conversation reads as one response instead of a bubble
 * plus a card.
 */
export function splitTranscript(interview: Interview): {
  entries: ChatEntry[];
  closing: InterviewTurn | null;
} {
  const turns = [...interview.turns];
  const last = turns[turns.length - 1];
  const closing =
    interview.status === 'completed' && last?.role === 'agent' ? last : null;
  if (closing) turns.pop();
  return {entries: turns.map(turnToEntry), closing};
}

/** The session state an interview snapshot is rendered into. */
export interface TranscriptSink extends Pick<
  HandlerDeps,
  'setInterview' | 'setDraft' | 'setConfirmed' | 'stageDraftSpec'
> {
  // Deliberately wider than HandlerDeps.setMessages: rendering a snapshot
  // replaces the whole log with plain entries, so the sink accepts any
  // replacement setter and must not require the session's stateful dispatch.
  // Do not narrow this to Dispatch<SetStateAction<ChatEntry[]>>.
  setMessages: (entries: ChatEntry[]) => void;
}

/**
 * Renders a resolved interview into the session: its transcript, and the plan
 * it derived once it completes.
 *
 * The server's copy is the whole conversation, so this replaces the message
 * log rather than appending to it. That is what lets a revision (an edited
 * prompt, a retried answer) drop the turns it invalidated: they are simply
 * absent from the snapshot that comes back, and every surviving bubble
 * carries the durable turn id it can be revised by.
 *
 * An interview that is *not* complete cannot leave a plan on screen. Staging
 * one is the completed branch's job, so any card left over from a derivation
 * the scientist has since withdrawn is cleared here.
 */
export function applyInterview(
  sink: TranscriptSink,
  interview: Interview,
): void {
  const {entries, closing} = splitTranscript(interview);
  sink.setMessages(entries);
  sink.setInterview(interview);
  if (closing) {
    sink.stageDraftSpec(interviewToRunSpec(interview), closing.created_at, {
      message: closing.content,
      reasoning: closing.reasoning ?? undefined,
      turnId: closing.id,
    });
    return;
  }
  sink.setDraft(null);
  sink.setConfirmed(null);
}
