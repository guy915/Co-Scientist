import {type RunMessage} from '@/api/runs';
import {type ChatEntry} from '../pages/chat_timeline_cards';

// Converts a run's persisted Q&A rows (GET /messages, filtered to
// kind === 'qa') into timeline bubbles on reopen/reload. Kept apart from
// chat_session_transcript.ts, which shapes the durable *interview*
// transcript -- a different lineage with its own turn ids and reasoning.

/** A persisted row's sender, as a chat bubble role. */
function qaRole(sender: RunMessage['sender']): ChatEntry['role'] {
  return sender === 'user' ? 'user' : 'assistant';
}

/**
 * Builds the Q&A bubbles for one run, in the order the rows arrived --
 * matching the shape a live ask already produces (see
 * chat_session_handlers_qa.ts), so a reload renders identically to a live
 * turn. Callers pass the full `GET /messages` result; only `kind === 'qa'`
 * rows are kept, since the same endpoint also returns steering messages.
 */
export function qaMessagesToEntries(rows: RunMessage[]): ChatEntry[] {
  return rows
    .filter(row => row.kind === 'qa')
    .map(row => ({
      id: `qa-${row.id}`,
      role: qaRole(row.sender),
      content: row.content,
      sources: row.meta?.sources,
      created_at: row.created_at,
    }));
}
