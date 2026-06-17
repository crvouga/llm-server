import { CHAT_COMPLETIONS_PATH } from './constants';

async function parseErrorResponse(response: Response) {
  try {
    const json = (await response.json()) as { error?: { message?: string } };
    return json.error?.message || `Request failed (${response.status})`;
  } catch {
    const text = await response.text();
    return text || `Request failed (${response.status})`;
  }
}

async function readSseStream(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  onDelta: (content: string) => void,
) {
  const decoder = new TextDecoder();
  let buffer = '';
  let full = '';
  let usage: Record<string, unknown> | null = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) return { content: full, usage };
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed.startsWith('data:')) continue;
      const data = trimmed.slice(5).trim();
      if (!data || data === '[DONE]') continue;
      try {
        const parsed = JSON.parse(data) as {
          choices?: Array<{ delta?: { content?: string } }>;
          usage?: Record<string, unknown>;
        };
        const delta = parsed.choices?.[0]?.delta?.content;
        if (typeof delta === 'string' && delta.length > 0) {
          full += delta;
          onDelta(full);
        }
        if (parsed.usage && typeof parsed.usage === 'object') {
          usage = parsed.usage;
        }
      } catch {
        /* ignore malformed SSE */
      }
    }
  }
}

function normalizeChatUsage(usage: Record<string, unknown> | null) {
  if (!usage || typeof usage !== 'object') return null;
  const promptTokens = Number(usage.prompt_tokens);
  const completionTokens = Number(usage.completion_tokens);
  if (!Number.isFinite(promptTokens) || !Number.isFinite(completionTokens)) return null;
  return { promptTokens, completionTokens };
}

export async function streamChatCompletion(
  messages: Array<{ role: string; content: string }>,
  model: string,
  onDelta: (content: string) => void,
  signal: AbortSignal,
) {
  const startedAt = performance.now();
  const response = await fetch(CHAT_COMPLETIONS_PATH, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model, messages, stream: true }),
    signal,
  });

  if (!response.ok) {
    throw new Error(await parseErrorResponse(response));
  }

  const contentType = response.headers.get('content-type') || '';
  if (!contentType.includes('text/event-stream') || !response.body) {
    const json = (await response.json()) as {
      choices?: Array<{ message?: { content?: string } }>;
      usage?: Record<string, unknown>;
    };
    const content = json.choices?.[0]?.message?.content ?? '';
    onDelta(content);
    const durationMs = performance.now() - startedAt;
    const usage = normalizeChatUsage(json.usage ?? null);
    return {
      content,
      durationMs,
      promptTokens: usage?.promptTokens ?? null,
      completionTokens: usage?.completionTokens ?? null,
    };
  }

  const result = await readSseStream(response.body.getReader(), onDelta);
  const durationMs = performance.now() - startedAt;
  const usage = normalizeChatUsage(result.usage);
  return {
    content: result.content,
    durationMs,
    promptTokens: usage?.promptTokens ?? null,
    completionTokens: usage?.completionTokens ?? null,
  };
}
