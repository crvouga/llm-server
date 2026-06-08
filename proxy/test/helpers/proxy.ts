import type { Hono } from 'hono';
import type { Env } from '../../src/index';
import type { TestExecutionContext } from './ctx';

type ProxyApp = Hono<{
  Bindings: Env;
  Variables: { requestId: string };
}>;

export interface ProxyRequestOptions {
  app: ProxyApp;
  databaseUrl: string;
  ctx: TestExecutionContext['ctx'];
  drain: TestExecutionContext['drain'];
  path?: string;
  method?: string;
  model?: string;
  body?: Record<string, unknown>;
  host?: string;
}

export async function proxyRequest(options: ProxyRequestOptions): Promise<Response> {
  const {
    app,
    databaseUrl,
    ctx,
    drain,
    path = '/v1/chat/completions',
    method = 'POST',
    model,
    body,
    host = 'proxy.test',
  } = options;

  const init: RequestInit = { method };
  if (method !== 'GET' && method !== 'HEAD') {
    init.headers = { 'content-type': 'application/json' };
    init.body = JSON.stringify(
      body ?? {
        model,
        messages: [{ role: 'user', content: 'hello' }],
      },
    );
  }

  const response = await app.fetch(
    new Request(`http://${host}${path}`, init),
    { DATABASE_URL: databaseUrl },
    ctx,
  );

  await drain();
  return response;
}
