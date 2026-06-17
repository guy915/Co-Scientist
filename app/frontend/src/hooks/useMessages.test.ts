import {describe, it, expect, vi, beforeEach, afterEach} from 'vitest';
import {renderHook, act, waitFor} from '@testing-library/react';
import type {Message} from '@/api/runs';
import {useMessages} from './useMessages';

// The api client is the external data seam; mock the network functions but keep
// askQuestionUrl real (it is a pure string builder the streaming path needs).
const listMessages = vi.fn<(runId: string) => Promise<Message[]>>();
const sendMessage =
  vi.fn<
    (
      runId: string,
      content: string,
      kind?: 'steering' | 'qa',
    ) => Promise<Message>
  >();
vi.mock('@/api/runs', () => ({
  listMessages: (runId: string) => listMessages(runId),
  sendMessage: (runId: string, content: string, kind?: 'steering' | 'qa') =>
    sendMessage(runId, content, kind),
  askQuestionUrl: (runId: string) => `/api/runs/${runId}/messages/ask`,
}));

/** Builds a minimal persisted Message for a run. */
function msg(id: number, content: string, sender: 'user' | 'system'): Message {
  return {
    id,
    run_id: 'run-1',
    sender,
    content,
    kind: 'steering',
    created_at: 0,
    applied: false,
  };
}

beforeEach(() => {
  listMessages.mockReset();
  sendMessage.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('useMessages', () => {
  it('loads and exposes the run messages on mount', async () => {
    listMessages.mockResolvedValue([
      msg(1, 'hello', 'user'),
      msg(2, 'world', 'system'),
    ]);

    const {result} = renderHook(() => useMessages('run-1', false));

    await waitFor(() => expect(result.current.messages).toHaveLength(2));
    expect(result.current.messages.map(m => m.content)).toEqual([
      'hello',
      'world',
    ]);
    expect(result.current.error).toBeNull();
    expect(listMessages).toHaveBeenCalledWith('run-1');
  });

  it('stays idle and fetches nothing when runId is null', async () => {
    const {result} = renderHook(() => useMessages(null, false));
    await waitFor(() => expect(listMessages).not.toHaveBeenCalled());
    expect(result.current.messages).toEqual([]);
  });

  it('records the error message when the fetch rejects', async () => {
    listMessages.mockRejectedValue(new Error('boom'));

    const {result} = renderHook(() => useMessages('run-1', false));

    await waitFor(() => expect(result.current.error).toBe('boom'));
    expect(result.current.messages).toEqual([]);
  });

  it('optimistically appends a steering message then swaps in the persisted one', async () => {
    listMessages.mockResolvedValue([]);
    const persisted: Message = {...msg(999, 'steer me', 'user'), applied: true};
    sendMessage.mockResolvedValue(persisted);

    const {result} = renderHook(() => useMessages('run-1', false));
    await waitFor(() => expect(listMessages).toHaveBeenCalled());

    await act(async () => {
      await result.current.sendSteering('steer me');
    });

    expect(sendMessage).toHaveBeenCalledWith('run-1', 'steer me', 'steering');
    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0]).toEqual(persisted);
  });

  it('rolls back the optimistic steering message when the send fails', async () => {
    listMessages.mockResolvedValue([]);
    sendMessage.mockRejectedValue(new Error('send failed'));

    const {result} = renderHook(() => useMessages('run-1', false));
    await waitFor(() => expect(listMessages).toHaveBeenCalled());

    await act(async () => {
      await result.current.sendSteering('steer me');
    });

    expect(result.current.messages).toEqual([]);
    expect(result.current.error).toBe('send failed');
  });

  it('streams chunks into the answer message and toggles isAnswering', async () => {
    // First call is the mount load. The reconciling fetchMessages() in
    // sendQuestion's finally block is fired un-awaited, so we keep it pending:
    // the asserted content then reflects what the stream loop actually
    // concatenated, not whatever a resolved refetch would have supplied.
    listMessages
      .mockResolvedValueOnce([])
      .mockReturnValue(new Promise<Message[]>(() => {}));

    // A ReadableStream of SSE lines emulating the /ask streaming endpoint.
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        const enc = new TextEncoder();
        controller.enqueue(
          enc.encode('data: {"type":"chunk","content":"Hello "}\n'),
        );
        controller.enqueue(
          enc.encode('data: {"type":"chunk","content":"world"}\n'),
        );
        controller.close();
      },
    });
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(body, {status: 200}));
    vi.stubGlobal('fetch', fetchMock);

    const {result} = renderHook(() => useMessages('run-1', false));
    await waitFor(() => expect(listMessages).toHaveBeenCalled());

    await act(async () => {
      await result.current.sendQuestion('what is up?');
    });

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(result.current.isAnswering).toBe(false);
    // The two SSE chunks 'Hello ' + 'world' were concatenated into the
    // optimistic answer message by the stream loop.
    const systemMsg = result.current.messages.find(m => m.sender === 'system');
    expect(systemMsg?.content).toBe('Hello world');
    const userMsg = result.current.messages.find(m => m.sender === 'user');
    expect(userMsg?.content).toBe('what is up?');
  });

  it('records an error when the ask request returns a non-ok response', async () => {
    listMessages.mockResolvedValue([]);
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response('nope', {status: 500}));
    vi.stubGlobal('fetch', fetchMock);

    const {result} = renderHook(() => useMessages('run-1', false));
    await waitFor(() => expect(listMessages).toHaveBeenCalled());

    await act(async () => {
      await result.current.sendQuestion('what is up?');
    });

    expect(result.current.isAnswering).toBe(false);
    expect(result.current.error).toBe('ask failed: 500');
  });
});
