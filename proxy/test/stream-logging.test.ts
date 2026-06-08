import { describe, expect, test } from 'bun:test';
import { buildLoggableStreamResponse, parseSseStream } from '../src/stream-logging';

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
    const stream = sseBody([
      'data: {"id":"chatcmpl-1","model":"test-model","choices":[{"delta":{"content":"hello"}}]}',
      '',
      'data: {"id":"chatcmpl-1","model":"test-model","choices":[],"usage":{"prompt_tokens":42,"completion_tokens":17,"total_tokens":59}}',
      '',
      'data: [DONE]',
      '',
    ]);

    const result = (await parseSseStream(stream)) as {
      usage?: { prompt_tokens?: number; completion_tokens?: number };
    };

    expect(result?.usage?.prompt_tokens).toBe(42);
    expect(result?.usage?.completion_tokens).toBe(17);
  });

  test('returns null for empty stream', async () => {
    const stream = sseBody([]);
    expect(await parseSseStream(stream)).toBeNull();
  });

  test('returns null when stream has no usage chunk', async () => {
    const stream = sseBody([
      'data: {"choices":[{"delta":{"content":"x"}}]}',
      '',
      'data: [DONE]',
      '',
    ]);
    expect(await parseSseStream(stream)).toBeNull();
  });

  test('skips malformed data lines', async () => {
    const stream = sseBody([
      'data: not-json',
      '',
      'data: {"usage":{"prompt_tokens":1,"completion_tokens":2}}',
      '',
    ]);

    const result = (await parseSseStream(stream)) as {
      usage?: { prompt_tokens?: number; completion_tokens?: number };
    };

    expect(result?.usage?.prompt_tokens).toBe(1);
    expect(result?.usage?.completion_tokens).toBe(2);
  });
});
