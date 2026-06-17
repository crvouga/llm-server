/** Default hybrid-reasoning models to non-thinking unless the client opts in. */

const CHAT_PATH_SUFFIXES = ['/chat/completions', '/messages'];

export function isChatCompletionPath(path: string): boolean {
  const normalized = path.replace(/\/+$/, '') || '/';
  return CHAT_PATH_SUFFIXES.some((suffix) => normalized === suffix || normalized.endsWith(suffix));
}

function extractTextContent(content: unknown): string {
  if (typeof content === 'string') {
    return content;
  }
  if (!Array.isArray(content)) {
    return '';
  }
  return content
    .map((block) => {
      if (!block || typeof block !== 'object') {
        return '';
      }
      const text = (block as Record<string, unknown>).text;
      return typeof text === 'string' ? text : '';
    })
    .join('');
}

function lastUserMessageText(messages: unknown): string {
  if (!Array.isArray(messages)) {
    return '';
  }
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const msg = messages[i];
    if (!msg || typeof msg !== 'object') {
      continue;
    }
    const record = msg as Record<string, unknown>;
    if (record.role === 'user') {
      return extractTextContent(record.content);
    }
  }
  return '';
}

function reasoningEffortRequestsThinking(body: Record<string, unknown>): boolean {
  const effort = body.reasoning_effort;
  if (typeof effort === 'string') {
    return effort.length > 0 && effort !== 'none';
  }
  if (effort && typeof effort === 'object') {
    const nested = (effort as Record<string, unknown>).effort;
    if (typeof nested === 'string') {
      return nested.length > 0 && nested !== 'none';
    }
  }
  const reasoning = body.reasoning;
  if (reasoning && typeof reasoning === 'object') {
    const nested = (reasoning as Record<string, unknown>).effort;
    if (typeof nested === 'string') {
      return nested.length > 0 && nested !== 'none';
    }
  }
  return false;
}

export function hasThinkingIntent(body: Record<string, unknown>): boolean {
  if (body.enable_thinking === true) {
    return true;
  }

  const kwargs = body.chat_template_kwargs;
  if (kwargs && typeof kwargs === 'object') {
    const templateKwargs = kwargs as Record<string, unknown>;
    if (templateKwargs.enable_thinking === true) {
      return true;
    }
    if (templateKwargs.preserve_thinking === true) {
      return true;
    }
  }

  if (reasoningEffortRequestsThinking(body)) {
    return true;
  }

  const lastUser = lastUserMessageText(body.messages);
  if (/\/think\b/i.test(lastUser)) {
    return true;
  }

  return false;
}

export function applyThinkingDefault(body: Record<string, unknown>): Record<string, unknown> {
  const existing = body.chat_template_kwargs;
  const templateKwargs =
    existing && typeof existing === 'object' ? { ...(existing as Record<string, unknown>) } : {};
  templateKwargs.enable_thinking = false;
  return { ...body, chat_template_kwargs: templateKwargs };
}

export function applyStreamUsageDefault(body: Record<string, unknown>): Record<string, unknown> {
  if (body.stream !== true) {
    return body;
  }

  const existing = body.stream_options;
  const streamOptions =
    existing && typeof existing === 'object' ? { ...(existing as Record<string, unknown>) } : {};

  if ('include_usage' in streamOptions) {
    return body;
  }

  return { ...body, stream_options: { ...streamOptions, include_usage: true } };
}

export async function prepareProxyRequestBody(
  request: Request,
  path: string,
): Promise<{ body: BodyInit | null; parsed: unknown | null }> {
  if (request.method === 'GET' || request.method === 'HEAD') {
    return { body: null, parsed: null };
  }

  if (request.method !== 'POST' || !isChatCompletionPath(path)) {
    return { body: request.body, parsed: null };
  }

  const contentType = request.headers.get('content-type') || '';
  if (!contentType.includes('application/json')) {
    return { body: request.body, parsed: null };
  }

  const raw = await request.text();
  if (!raw.trim()) {
    return { body: raw, parsed: null };
  }

  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    const withThinking = hasThinkingIntent(parsed) ? parsed : applyThinkingDefault(parsed);
    const outbound = applyStreamUsageDefault(withThinking);
    const serialized = JSON.stringify(outbound);
    return { body: serialized, parsed: outbound };
  } catch {
    return { body: raw, parsed: null };
  }
}
