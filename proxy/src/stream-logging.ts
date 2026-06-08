/** Parse SSE chat completion streams for usage logging. */

export interface StreamParseResult {
  responseBody: unknown | null;
  durationMs: number;
  ttftMs: number | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function hasUsage(value: unknown): value is Record<string, unknown> & { usage: unknown } {
  return isRecord(value) && value.usage !== undefined && value.usage !== null;
}

function deltaHasContent(delta: unknown): boolean {
  if (!isRecord(delta)) {
    return false;
  }
  for (const value of Object.values(delta)) {
    if (value === undefined || value === null) {
      continue;
    }
    if (typeof value === 'string') {
      if (value.length > 0) {
        return true;
      }
      continue;
    }
    return true;
  }
  return false;
}

export function isContentChunk(chunk: unknown): boolean {
  if (!isRecord(chunk) || !Array.isArray(chunk.choices)) {
    return false;
  }

  for (const choice of chunk.choices) {
    if (!isRecord(choice)) {
      continue;
    }
    if (deltaHasContent(choice.delta)) {
      return true;
    }
  }

  return false;
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
  startedAt: number,
): Promise<StreamParseResult> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  const chunks: unknown[] = [];
  let ttftMs: number | null = null;

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
        const chunkCountBefore = chunks.length;
        parseSseLine(line, chunks);
        if (ttftMs === null) {
          for (let i = chunkCountBefore; i < chunks.length; i += 1) {
            if (isContentChunk(chunks[i])) {
              ttftMs = Date.now() - startedAt;
              break;
            }
          }
        }
        newlineIndex = buffer.indexOf('\n');
      }
    }

    buffer += decoder.decode();
    if (buffer.trim()) {
      const chunkCountBefore = chunks.length;
      parseSseLine(buffer, chunks);
      if (ttftMs === null) {
        for (let i = chunkCountBefore; i < chunks.length; i += 1) {
          if (isContentChunk(chunks[i])) {
            ttftMs = Date.now() - startedAt;
            break;
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }

  const durationMs = Math.max(1, Date.now() - startedAt);
  const normalizedTtftMs = ttftMs === null ? null : Math.min(ttftMs, Math.max(0, durationMs - 1));

  return {
    responseBody: buildLoggableStreamResponse(chunks),
    durationMs,
    ttftMs: normalizedTtftMs,
  };
}
