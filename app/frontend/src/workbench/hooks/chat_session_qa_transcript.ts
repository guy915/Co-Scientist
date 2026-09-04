import {type RunMessage} from '@/api/runs';
import {type ChatEntry} from '../pages/chat_timeline_cards';

// Converts a run's persisted message rows (GET /messages) into the pieces a
// reopened chat rebuilds itself from: the bubbles for its Q&A exchanges and
// its start request, and the Agent's start announcement, which is not a
// bubble at all but the session card's lead-in. Kept apart from
// chat_session_transcript.ts, which shapes the durable *interview*
// transcript -- a different lineage with its own turn ids and reasoning.

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
