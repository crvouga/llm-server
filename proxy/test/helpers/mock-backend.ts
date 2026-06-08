/** In-process OpenAI-compatible mock backend for proxy e2e tests. */

export interface MockRouteOverride {
  pathSuffix: string;
  method?: string;
  status?: number;
  contentType?: string;
  body?: unknown | ((request: Request) => unknown | Promise<unknown>);
}

export interface MockBackendOptions {
  model: string;
  promptTokens?: number;
  completionTokens?: number;
  usageForRequest?: (request: Request) => { promptTokens: number; completionTokens: number };
  routes?: MockRouteOverride[];
}

export interface MockBackend {
  url: string;
  requests: Request[];
  stop: () => void;
}

function matchRoute(
  request: Request,
  route: MockRouteOverride,
): boolean {
  const url = new URL(request.url);
  const method = route.method ?? 'POST';
  return request.method === method && url.pathname.endsWith(route.pathSuffix);
}

async function buildRouteResponse(
  request: Request,
  route: MockRouteOverride,
): Promise<Response> {
  const status = route.status ?? 200;
  const contentType = route.contentType ?? 'application/json';

  if (contentType.includes('application/json')) {
    const body =
      typeof route.body === 'function' ? await route.body(request) : route.body ?? {};
    return Response.json(body, { status });
  }

  const text = typeof route.body === 'string' ? route.body : 'plain text response';
  return new Response(text, {
    status,
    headers: { 'content-type': contentType },
  });
}

async function defaultChatResponse(
  request: Request,
  options: MockBackendOptions,
): Promise<Response> {
  let body: { model?: string } = {};
  try {
    body = (await request.json()) as { model?: string };
  } catch {
    // GET and non-JSON bodies fall through
  }

  const model = body.model ?? options.model;
  const usage = options.usageForRequest?.(request) ?? {
    promptTokens: options.promptTokens ?? 0,
    completionTokens: options.completionTokens ?? 0,
  };

  return Response.json({
    id: 'chatcmpl-test',
    object: 'chat.completion',
    created: Math.floor(Date.now() / 1000),
    model,
    choices: [
      {
        index: 0,
        message: { role: 'assistant', content: 'test response' },
        finish_reason: 'stop',
      },
    ],
    usage: {
      prompt_tokens: usage.promptTokens,
      completion_tokens: usage.completionTokens,
      total_tokens: usage.promptTokens + usage.completionTokens,
    },
  });
}

export function startMockBackend(options: MockBackendOptions): MockBackend {
  const requests: Request[] = [];

  const server = Bun.serve({
    port: 0,
    async fetch(request) {
      requests.push(request.clone());

      const url = new URL(request.url);

      if (request.method === 'GET' && url.pathname.endsWith('/models')) {
        return Response.json({
          object: 'list',
          data: [{ id: options.model, object: 'model' }],
        });
      }

      for (const route of options.routes ?? []) {
        if (matchRoute(request, route)) {
          return buildRouteResponse(request, route);
        }
      }

      if (
        url.pathname.endsWith('/chat/completions') ||
        url.pathname.endsWith('/messages')
      ) {
        return defaultChatResponse(request, options);
      }

      return new Response('not found', { status: 404 });
    },
  });

  return {
    url: `http://127.0.0.1:${server.port}`,
    requests,
    stop: () => server.stop(true),
  };
}
