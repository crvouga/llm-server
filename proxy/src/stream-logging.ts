/** Parse SSE chat completion streams for usage logging. */

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function hasUsage(value: unknown): value is Record<string, unknown> & { usage: unknown } {
  return isRecord(value) && value.usage !== undefined && value.usage !== null;
}

export function buildLoggableStreamResponse(chunks: unknown[]): unknown | null {
  if (chunks.length === 0) {
    return null;
  }

  let usageChunk: Record<string, unknown> | null = null;
  for (let i = chunks.length - 1; i >= 0; i -= 1) {
    const chunk = chunks[i];
    if (hasUsage(chunk)) {
      usageChunk = chunk;
      break;
    }
  }

  if (!usageChunk) {
    return null;
  }

  const first = chunks.find(isRecord) ?? null;
  const id =
    (typeof usageChunk.id === 'string' ? usageChunk.id : null) ??
    (first && typeof first.id === 'string' ? first.id : null);
  const model =
    (typeof usageChunk.model === 'string' ? usageChunk.model : null) ??
    (first && typeof first.model === 'string' ? first.model : null);

  return {
    id,
    model,
    object: 'chat.completion',
    usage: usageChunk.usage,
  };
}

function parseSseLine(line: string, chunks: unknown[]): void {
  const trimmed = line.trimEnd();
  if (!trimmed.startsWith('data:')) {
    return;
  }

  const data = trimmed.slice(5).trimStart();
  if (!data || data === '[DONE]') {
    return;
  }

  try {
    chunks.push(JSON.parse(data));
  } catch {
    // Skip malformed JSON lines
  }
}

export async function parseSseStream(
  stream: ReadableStream<Uint8Array>,
): Promise<unknown | null> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  const chunks: unknown[] = [];

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }

      buffer += decoder.decode(value, { stream: true });

      let newlineIndex = buffer.indexOf('\n');
      while (newlineIndex !== -1) {
        const line = buffer.slice(0, newlineIndex);
        buffer = buffer.slice(newlineIndex + 1);
        parseSseLine(line, chunks);
        newlineIndex = buffer.indexOf('\n');
      }
    }

    buffer += decoder.decode();
    if (buffer.trim()) {
      parseSseLine(buffer, chunks);
    }
  } finally {
    reader.releaseLock();
  }

  return buildLoggableStreamResponse(chunks);
}
