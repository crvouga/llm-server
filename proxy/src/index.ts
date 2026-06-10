// Transparent LLM Proxy with Raw Request Logging
// Forwards all requests to LM Studio and logs raw request/response data to PostgreSQL

import { neon, NeonDbError } from '@neondatabase/serverless';
import { serveStatic } from 'hono/bun';
import { Hono } from 'hono';

import { fetchBackendUrl } from './proxy-state';
import { waitUntil } from './wait-until';
import { parseSseStream } from './stream-logging';
import { prepareProxyRequestBody } from './thinking-default';
import { uiRoute } from './ui';

export interface Env {
  DATABASE_URL: string;
}

type AppEnv = {
  Bindings: Env;
  Variables: {
    requestId: string;
  };
};

function generateRequestId(): string {
  try {
    return crypto.randomUUID();
  } catch {
    const chars = '0123456789abcdef';
    let id = Date.now().toString(16);
    for (let i = 0; i < 12; i++) {
      id += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    return id;
  }
}

function headersToObject(headers: Headers): Record<string, string> {
  const obj: Record<string, string> = {};
  headers.forEach((value, key) => {
    obj[key] = value;
  });
  return obj;
}

interface LogTiming {
  durationMs?: number | null;
  ttftMs?: number | null;
}

async function logRequest(
  env: Env,
  requestId: string,
  method: string,
  path: string,
  query: URLSearchParams,
  requestHeaders: Headers,
  body: unknown | null,
  statusCode: number,
  responseHeaders: Headers,
  responseBody: unknown | null,
  errorMessage?: string,
  timing?: LogTiming,
): Promise<void> {
  if (!env.DATABASE_URL) {
    console.warn('DATABASE_URL not configured, skipping request logging');
    return;
  }

  try {
    const sql = neon(env.DATABASE_URL);

    const queryParamsObj: Record<string, string> = {};
    query.forEach((value, key) => {
      queryParamsObj[key] = value;
    });

    const requestBody = body === null ? null : JSON.stringify(body);
    const responseBodyJson = responseBody === null ? null : JSON.stringify(responseBody);

    await sql`
      INSERT INTO llm_proxy.http_log (
        id, created_at, request_method, request_path, request_query_params,
        request_headers, request_body, response_status_code, response_headers,
        response_body, response_error_message, duration_ms, ttft_ms
      )
      VALUES (
        ${requestId},
        ${new Date().toISOString()},
        ${method},
        ${path},
        ${JSON.stringify(queryParamsObj)}::jsonb,
        ${JSON.stringify(headersToObject(requestHeaders))}::jsonb,
        ${requestBody}::jsonb,
        ${statusCode},
        ${JSON.stringify(headersToObject(responseHeaders))}::jsonb,
        ${responseBodyJson}::jsonb,
        ${errorMessage || null},
        ${timing?.durationMs ?? null},
        ${timing?.ttftMs ?? null}
      )
    `;
  } catch (error) {
    const code = error instanceof NeonDbError ? error.code : 'unknown';
    console.error(`Request logging failed (code: ${code ?? 'unknown'})`);
  }
}

function buildBackendRequestHeaders(request: Request, requestUrl: URL): Headers {
  const requestHeaders = new Headers();
  request.headers.forEach((value, key) => {
    if (key.toLowerCase() !== 'host') {
      requestHeaders.set(key, value);
    }
  });
  requestHeaders.set('X-Forwarded-Host', requestUrl.host);

  const clientIp =
    request.headers.get('CF-Connecting-IP') ??
    request.headers.get('Fly-Client-IP') ??
    request.headers.get('X-Forwarded-For');
  if (clientIp) {
    requestHeaders.set('X-Forwarded-For', clientIp);
  }

  return requestHeaders;
}

async function readJsonResponseBody(response: Response): Promise<unknown | null> {
  const contentType = response.headers.get('content-type') || '';
  if (!contentType.includes('application/json')) {
    return null;
  }

  try {
    return await response.clone().json();
  } catch {
    return null;
  }
}

export function createApp(): Hono<AppEnv> {
  const app = new Hono<AppEnv>();

  app.use('*', async (c, next) => {
    const requestId = generateRequestId();
    c.set('requestId', requestId);
    console.log(`[${requestId}] ${c.req.method} ${c.req.path}`);
    await next();
  });

  app.route('/', uiRoute);

  app.use('*', serveStatic({ root: './public' }));

  app.all('*', async (c) => {
    const env = c.env;
    const request = c.req.raw;
    const requestId = c.get('requestId');
    const requestUrl = new URL(request.url);
    const path = c.req.path || '/';

    if (!env.DATABASE_URL) {
      return c.json({ error: 'Proxy not configured', details: 'DATABASE_URL is not set' }, 503);
    }

    const backendUrl = await fetchBackendUrl(env.DATABASE_URL);
    if (!backendUrl) {
      return c.json(
        {
          error: 'Proxy not configured',
          details: 'Set llm_proxy.config.backend_url',
        },
        503,
      );
    }

    const backendPath = requestUrl.pathname + requestUrl.search;
    const targetUrl = `${backendUrl}${backendPath}`;

    const { body: requestBody, parsed: requestPayload } = await prepareProxyRequestBody(
      request,
      path,
    );
    const requestHeaders = buildBackendRequestHeaders(request, requestUrl);
    if (typeof requestBody === 'string') {
      requestHeaders.set('Content-Length', String(new TextEncoder().encode(requestBody).length));
    }

    const init: RequestInit = {
      method: request.method,
      headers: requestHeaders,
      body: requestBody,
    };

    try {
      const startedAt = Date.now();
      const response = await fetch(targetUrl, init);
      const contentType = response.headers.get('content-type') || '';

      if (contentType.includes('text/event-stream') && response.body) {
        const [clientStream, logStream] = response.body.tee();

        waitUntil(
          c.executionCtx,
          (async () => {
            const { responseBody, durationMs, ttftMs } = await parseSseStream(logStream, startedAt);
            await logRequest(
              env,
              requestId,
              request.method,
              path,
              requestUrl.searchParams,
              request.headers,
              requestPayload,
              response.status,
              response.headers,
              responseBody,
              undefined,
              { durationMs, ttftMs },
            );
          })(),
        );

        console.log(`[${requestId}] ${response.status} ${path} (stream)`);

        return new Response(clientStream, {
          status: response.status,
          statusText: response.statusText,
          headers: response.headers,
        });
      }

      const responseBody = await readJsonResponseBody(response);
      const durationMs = Math.max(1, Date.now() - startedAt);

      waitUntil(
        c.executionCtx,
        logRequest(
          env,
          requestId,
          request.method,
          path,
          requestUrl.searchParams,
          request.headers,
          requestPayload,
          response.status,
          response.headers,
          responseBody,
          undefined,
          { durationMs, ttftMs: null },
        ),
      );

      console.log(`[${requestId}] ${response.status} ${path}`);

      return new Response(response.body, {
        status: response.status,
        statusText: response.statusText,
        headers: response.headers,
      });
    } catch (error) {
      waitUntil(
        c.executionCtx,
        logRequest(
          env,
          requestId,
          request.method,
          path,
          requestUrl.searchParams,
          request.headers,
          null,
          503,
          new Headers(),
          { error: 'Backend unavailable', details: String(error) },
          error instanceof Error ? error.message : String(error),
        ),
      );

      return c.json({ error: 'Backend unavailable', details: String(error) }, 503);
    }
  });

  return app;
}
