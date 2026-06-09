import { CHAT_COMPLETIONS_PATH } from '../constants';
import { MODELS_API_PATH } from '../../shared/constants';
import type { ChatMessage } from '../types';

export async function fetchAvailableModels(): Promise<string[]> {
  const response = await fetch(MODELS_API_PATH);
  if (!response.ok) {
    return [];
  }

  try {
    const json = (await response.json()) as { data?: Array<{ id?: string }> };
    return (json.data ?? [])
      .map((entry) => entry.id)
      .filter((id): id is string => typeof id === 'string' && id.length > 0);
  } catch {
    return [];
  }
}

export async function streamChatCompletion(
  messages: ChatMessage[],
  model: string,
  onDelta: (content: string) => void,
): Promise<string> {
  const response = await fetch(CHAT_COMPLETIONS_PATH, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model,
      messages,
      stream: true,
    }),
  });

  if (!response.ok) {
    let details = `Request failed (${response.status})`;
    try {
      const json = (await response.json()) as { error?: { message?: string } };
      if (json.error?.message) {
        details = json.error.message;
      }
    } catch {
      const text = await response.text();
      if (text) {
        details = text;
      }
    }
    throw new Error(details);
  }

  const contentType = response.headers.get('content-type') || '';
  if (!contentType.includes('text/event-stream') || !response.body) {
    const json = (await response.json()) as {
      choices?: Array<{ message?: { content?: string } }>;
    };
    const content = json.choices?.[0]?.message?.content ?? '';
    onDelta(content);
    return content;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let full = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed.startsWith('data:')) {
        continue;
      }

      const data = trimmed.slice(5).trim();
      if (!data || data === '[DONE]') {
        continue;
      }

      try {
        const parsed = JSON.parse(data) as {
          choices?: Array<{ delta?: { content?: string } }>;
        };
        const delta = parsed.choices?.[0]?.delta?.content;
        if (typeof delta === 'string' && delta.length > 0) {
          full += delta;
          onDelta(full);
        }
      } catch {
        // Ignore malformed SSE chunks.
      }
    }
  }

  return full;
}
