import { describe, expect, test } from 'bun:test';
import {
  buildLoggableStreamResponse,
  isContentChunk,
  parseSseStream,
} from '../src/stream-logging';

function sseBody(lines: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  const text = lines.join('\n');
  return new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode(text));
      controller.close();
    },
  });
}

function delayedSseBody(
  chunks: Array<{ delayMs: number; line: string }>,
): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    async start(controller) {
      for (const chunk of chunks) {
        if (chunk.delayMs > 0) {
          await new Promise((resolve) => setTimeout(resolve, chunk.delayMs));
        }
        controller.enqueue(encoder.encode(`${chunk.line}\n`));
      }
      controller.close();
    },
  });
}

describe('isContentChunk', () => {
  test('returns true for chunks with delta content', () => {
    expect(
      isContentChunk({
        choices: [{ delta: { content: 'hi' } }],
      }),
    ).toBe(true);
  });

  test('returns false for usage-only chunks', () => {
    expect(
      isContentChunk({
        choices: [],
        usage: { prompt_tokens: 1, completion_tokens: 2 },
      }),
    ).toBe(false);
  });

  test('returns false for empty delta', () => {
    expect(
      isContentChunk({
        choices: [{ delta: {} }],
      }),
    ).toBe(false);
  });

  test('returns false for empty content string', () => {
    expect(
      isContentChunk({
        choices: [{ delta: { content: '' } }],
      }),
    ).toBe(false);
  });

  test('returns true for tool_calls delta', () => {
    expect(
      isContentChunk({
        choices: [{ delta: { tool_calls: [{ index: 0, id: 'call_1', type: 'function' }] } }],
      }),
    ).toBe(true);
  });

  test('returns true for reasoning_content delta', () => {
    expect(
      isContentChunk({
        choices: [{ delta: { reasoning_content: 'thinking...' } }],
      }),
    ).toBe(true);
  });

  test('returns true for role-only delta (current TTFT behavior)', () => {
    expect(
      isContentChunk({
        choices: [{ delta: { role: 'assistant' } }],
      }),
    ).toBe(true);
  });
});

describe('buildLoggableStreamResponse', () => {
  test('returns null for empty chunks', () => {
    expect(buildLoggableStreamResponse([])).toBeNull();
  });

  test('returns null when no chunk contains usage', () => {
    const chunks = [
      { id: '1', choices: [{ delta: { content: 'hi' } }] },
      { id: '1', choices: [{ delta: { content: ' there' } }] },
    ];
    expect(buildLoggableStreamResponse(chunks)).toBeNull();
  });

  test('extracts usage from the last chunk that contains it', () => {
    const chunks = [
      { id: 'chatcmpl-1', model: 'test-model', choices: [{ delta: { content: 'hi' } }] },
      {
        id: 'chatcmpl-1',
        model: 'test-model',
        choices: [],
        usage: { prompt_tokens: 10, completion_tokens: 5, total_tokens: 15 },
      },
    ];

    expect(buildLoggableStreamResponse(chunks)).toEqual({
      id: 'chatcmpl-1',
      model: 'test-model',
      object: 'chat.completion',
      usage: { prompt_tokens: 10, completion_tokens: 5, total_tokens: 15 },
    });
  });
});

describe('parseSseStream', () => {
  test('parses multi-chunk SSE with usage and [DONE]', async () => {
    const startedAt = Date.now();
    const stream = sseBody([
      'data: {"id":"chatcmpl-1","model":"test-model","choices":[{"delta":{"content":"hello"}}]}',
      '',
      'data: {"id":"chatcmpl-1","model":"test-model","choices":[],"usage":{"prompt_tokens":42,"completion_tokens":17,"total_tokens":59}}',
      '',
      'data: [DONE]',
      '',
    ]);

    const result = await parseSseStream(stream, startedAt);

    expect(result.responseBody).toMatchObject({
      usage: { prompt_tokens: 42, completion_tokens: 17 },
    });
    expect(result.durationMs).toBeGreaterThanOrEqual(0);
    expect(result.ttftMs).toBeGreaterThanOrEqual(0);
    expect(result.ttftMs).toBeLessThanOrEqual(result.durationMs);
  });

  test('returns null response body for empty stream', async () => {
    const stream = sseBody([]);
    const result = await parseSseStream(stream, Date.now());
    expect(result.responseBody).toBeNull();
  });

  test('returns null response body when stream has no usage chunk', async () => {
    const stream = sseBody([
      'data: {"choices":[{"delta":{"content":"x"}}]}',
      '',
      'data: [DONE]',
      '',
    ]);
    const result = await parseSseStream(stream, Date.now());
    expect(result.responseBody).toBeNull();
  });

  test('skips malformed data lines', async () => {
    const stream = sseBody([
      'data: not-json',
      '',
      'data: {"usage":{"prompt_tokens":1,"completion_tokens":2}}',
      '',
    ]);

    const result = await parseSseStream(stream, Date.now());
    expect(result.responseBody).toMatchObject({
      usage: { prompt_tokens: 1, completion_tokens: 2 },
    });
  });

  test('returns null ttft for usage-only stream', async () => {
    const startedAt = Date.now();
    const stream = sseBody([
      'data: {"choices":[],"usage":{"prompt_tokens":3,"completion_tokens":7,"total_tokens":10}}',
      '',
      'data: [DONE]',
      '',
    ]);

    const result = await parseSseStream(stream, startedAt);

    expect(result.responseBody).toMatchObject({
      usage: { prompt_tokens: 3, completion_tokens: 7 },
    });
    expect(result.ttftMs).toBeNull();
    expect(result.durationMs).toBeGreaterThanOrEqual(1);
  });

  test('records ttft before duration when chunks are delayed', async () => {
    const startedAt = Date.now();
    const stream = delayedSseBody([
      {
        delayMs: 0,
        line: 'data: {"choices":[{"delta":{"content":"hello"}}]}',
      },
      { delayMs: 80, line: '' },
      {
        delayMs: 0,
        line: 'data: {"choices":[],"usage":{"prompt_tokens":1,"completion_tokens":2}}',
      },
      { delayMs: 0, line: 'data: [DONE]' },
    ]);

    const result = await parseSseStream(stream, startedAt);

    expect(result.ttftMs).not.toBeNull();
    expect(result.durationMs).toBeGreaterThanOrEqual(80);
    expect(result.ttftMs!).toBeLessThan(result.durationMs);
  });
});
