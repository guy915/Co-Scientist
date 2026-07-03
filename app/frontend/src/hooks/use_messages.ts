import {useCallback, useEffect, useRef, useState} from 'react';
import {
  answerOfflineQuestion,
  askQuestionUrl,
  canUseOfflineRun,
  listMessages,
  type Message,
  type SourceRef,
  sendMessage,
} from '@/api/runs';

/** State and actions returned by {@link useMessages}. */
export interface UseMessagesResult {
  messages: Message[];
  isAnswering: boolean;
  error: string | null;
  sendSteering: (content: string) => Promise<void>;
  sendQuestion: (question: string) => Promise<void>;
}

/**
 * Loads a run's messages, polling while it is active, and exposes helpers to
 * send steering messages and ask streamed Q&A questions with optimistic UI.
 *
 * @param runId Run to load messages for, or null to stay idle.
 * @param isRunActive Whether to poll for new messages on an interval.
 * @returns The message list, answering state, last error, and send actions.
 */
export function useMessages(
  runId: string | null,
  isRunActive: boolean,
): UseMessagesResult {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isAnswering, setIsAnswering] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const localSteeringRef = useRef<Map<number, Message>>(new Map());

  const fetchMessages = useCallback(async () => {
    if (!runId) return;
    try {
      const msgs = await listMessages(runId);
      const fetchedIds = new Set(msgs.map(message => message.id));
      for (const id of fetchedIds) {
        localSteeringRef.current.delete(id);
      }
      const localMessages = [...localSteeringRef.current.values()].filter(
        message => message.run_id === runId && !fetchedIds.has(message.id),
      );
      setMessages(
        [...msgs, ...localMessages].sort(
          (a, b) => a.created_at - b.created_at || a.id - b.id,
        ),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [runId]);

  useEffect(() => {
    if (!runId) {
      setMessages([]);
      setError(null);
      return;
    }
    void fetchMessages();
    if (isRunActive) {
      pollRef.current = setInterval(() => void fetchMessages(), 3000);
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [fetchMessages, isRunActive]);

  const sendSteering = useCallback(
    async (content: string) => {
      if (!runId) return;
      const optimistic: Message = {
        id: Date.now(),
        run_id: runId,
        sender: 'user',
        content,
        kind: 'steering',
        created_at: Date.now() / 1000,
        applied: false,
        status: 'queued',
      };
      localSteeringRef.current.set(optimistic.id, optimistic);
      setMessages(prev => [...prev, optimistic]);
      try {
        const msg = await sendMessage(runId, content, 'steering');
        localSteeringRef.current.delete(optimistic.id);
        localSteeringRef.current.set(msg.id, msg);
        setMessages(prev => prev.map(m => (m.id === optimistic.id ? msg : m)));
      } catch (e) {
        localSteeringRef.current.delete(optimistic.id);
        setMessages(prev => prev.filter(m => m.id !== optimistic.id));
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [runId],
  );

  const sendQuestion = useCallback(
    async (question: string) => {
      if (!runId || isAnswering) return;
      setIsAnswering(true);

      const questionMsg: Message = {
        id: Date.now(),
        run_id: runId,
        sender: 'user',
        content: question,
        kind: 'qa',
        created_at: Date.now() / 1000,
        applied: false,
      };
      setMessages(prev => [...prev, questionMsg]);

      const answerMsg: Message = {
        id: Date.now() + 1,
        run_id: runId,
        sender: 'system',
        content: '',
        kind: 'qa',
        created_at: Date.now() / 1000,
        applied: false,
      };
      setMessages(prev => [...prev, answerMsg]);

      try {
        const url = askQuestionUrl(runId);
        const res = await fetch(url, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({question}),
        });
        if (!res.ok || !res.body) throw new Error(`ask failed: ${res.status}`);

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const {done, value} = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, {stream: true});
          const lines = buffer.split('\n');
          buffer = lines.pop() ?? '';
          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            try {
              const event = JSON.parse(line.slice(6)) as {
                type: string;
                content?: string;
                sources?: SourceRef[];
              };
              if (event.type === 'chunk' && event.content) {
                const chunk = event.content;
                setMessages(prev =>
                  prev.map(m =>
                    m.id === answerMsg.id
                      ? {...m, content: m.content + chunk}
                      : m,
                  ),
                );
              } else if (event.type === 'sources' && event.sources) {
                const sources = event.sources;
                setMessages(prev =>
                  prev.map(m =>
                    m.id === answerMsg.id ? {...m, meta: {sources}} : m,
                  ),
                );
              }
            } catch {
              // ignore malformed SSE line
            }
          }
        }
      } catch (e) {
        if (canUseOfflineRun(runId)) {
          const answer = answerOfflineQuestion(runId, question);
          setMessages(prev =>
            prev.map(m =>
              m.id === answerMsg.id
                ? {
                    ...answer,
                    id: answerMsg.id,
                    created_at: answerMsg.created_at,
                  }
                : m,
            ),
          );
        } else {
          setError(e instanceof Error ? e.message : String(e));
        }
      } finally {
        setIsAnswering(false);
        void fetchMessages();
      }
    },
    [runId, isAnswering, fetchMessages],
  );

  return {messages, isAnswering, error, sendSteering, sendQuestion};
}
