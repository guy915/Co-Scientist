import {type Interview, type InterviewTurn, type RunMessage} from '@/api/runs';
import {interviewToRunSpec} from '../run_spec';
import {type ChatEntry} from '../pages/chat_timeline_bubble';
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
    // Rides with the bubble exactly as persisted: a fallback-authored turn
    // keeps its marker through every rebuild of the log.
    fallback: turn.fallback || undefined,
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
    const intro = {
      message: closing.content,
      reasoning: closing.reasoning ?? undefined,
      turnId: closing.id,
      // The closing turn becomes the plan card's lead-in instead of a
      // bubble, so its fallback marker rides with it there.
      fallback: closing.fallback || undefined,
    };
    // A chat that already started a run has no plan left to edit. Staging
    // one anyway put Start research live beside a card saying the run was
    // under way -- one click from a second run on the same goal. The
    // server's own answer is used rather than the run the workspace may or
    // may not have looked up yet, so reopening cannot depend on which of
    // the two loads lands first. Editing a settled plan is still offered,
    // by the confirmed card's own Edit, which stages a draft deliberately.
    if (interview.run_id) {
      sink.setDraft(null);
      sink.setConfirmed({
        spec: interviewToRunSpec(interview),
        createdAt: closing.created_at,
        intro: intro.message,
        reasoning: intro.reasoning,
        turnId: intro.turnId,
        fallback: intro.fallback,
      });
      return;
    }
    sink.stageDraftSpec(
      interviewToRunSpec(interview),
      closing.created_at,
      intro,
    );
    return;
  }
  sink.setDraft(null);
  sink.setConfirmed(null);
}

// Converts a run's persisted message rows (GET /messages) into the pieces a
// reopened chat rebuilds itself from: the bubbles for its Q&A exchanges and
// its start request, and the Agent's start announcement, which is not a
// bubble at all but the session card's lead-in. Interview turns above use
// their own durable turn ids and reasoning.

/**
 * The Agent's answer to the scientist's start request, as it is put back on
 * the session card (see run_start_announcement.py for the rows it comes
 * from). `at` is the reply's own timestamp, which is what re-anchors the card
 * *below* the request that produced it -- the run was created first, so the
 * run's own creation time would sort the card above its own prompt.
 */
export interface RehydratedAnnouncement {
  intro: string;
  reasoning?: string;
  at: number;
}

/** A persisted row's sender, as a chat bubble role. */
function qaRole(sender: RunMessage['sender']): ChatEntry['role'] {
  return sender === 'user' ? 'user' : 'assistant';
}

/** One persisted row as a timeline bubble. */
function rowToEntry(row: RunMessage): ChatEntry {
  return {
    id: `qa-${row.id}`,
    role: qaRole(row.sender),
    content: row.content,
    reasoning: row.meta?.reasoning,
    sources: row.meta?.sources,
    created_at: row.created_at,
  };
}

// Whether a row belongs in the timeline as a bubble of its own: every Q&A
// row, plus the scientist's own start request. The Agent's reply to that
// request is deliberately absent -- it is the card's lead-in, exactly as a
// completed interview's closing turn is the plan card's (see
// chat_session_transcript.ts::splitTranscript).
function isBubbleRow(row: RunMessage): boolean {
  if (row.kind === 'qa') return true;
  return row.kind === 'start' && row.sender === 'user';
}

/**
 * Builds the Q&A bubbles for one run, in the order the rows arrived --
 * matching the shape a live ask already produces (see
 * chat_session_handlers_qa.ts), so a reload renders identically to a live
 * turn. Callers pass the full `GET /messages` result; steering rows are
 * dropped, since the same endpoint returns those too.
 */
export function qaMessagesToEntries(rows: RunMessage[]): ChatEntry[] {
  return rows.filter(isBubbleRow).map(rowToEntry);
}

/**
 * Finds the Agent's start announcement among a run's persisted rows.
 *
 * The *first* such reply, not the last: a retried start, or the same chat
 * open in two tabs, can leave more than one, and the card has one lead-in.
 * Null for a run started before the announcement existed, which is what
 * leaves the card on its standby copy.
 */
export function runStartAnnouncement(
  rows: RunMessage[],
): RehydratedAnnouncement | null {
  const reply = rows.find(
    row => row.kind === 'start' && row.sender === 'system',
  );
  if (!reply) return null;
  return {
    intro: reply.content,
    reasoning: reply.meta?.reasoning,
    at: reply.created_at,
  };
}
