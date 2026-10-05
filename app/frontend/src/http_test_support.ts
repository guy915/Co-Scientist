import {vi} from 'vitest';

export function fetchMock() {
  return globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
}

export function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

export function errorResponse(status: number, text = 'boom'): Response {
  return {
    ok: false,
    status,
    statusText: 'Error',
    body: null,
    json: async () => ({}),
    text: async () => text,
  } as unknown as Response;
}

export class FakeSseBody {
  private controller: ReadableStreamDefaultController<Uint8Array> | null = null;
  readonly stream = new ReadableStream<Uint8Array>({
    start: controller => {
      this.controller = controller;
    },
  });
  private readonly encoder = new TextEncoder();

  push(frame: unknown): void {
    this.pushRaw(JSON.stringify(frame));
  }

  pushRaw(data: string): void {
    this.controller?.enqueue(this.encoder.encode(`data: ${data}\n\n`));
  }

  end(): void {
    this.controller?.close();
  }
}

export function streamingResponse(body: FakeSseBody): Response {
  return {
    ok: true,
    status: 200,
    statusText: 'OK',
    body: body.stream,
    text: async () => '',
  } as unknown as Response;
}
