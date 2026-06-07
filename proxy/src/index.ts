// Transparent LLM Proxy with Raw Request Logging
// Forwards all requests to LM Studio and logs raw request/response data to PostgreSQL

import { neon, NeonDbError } from '@neondatabase/serverless';
import { Hono } from 'hono';

import { fetchBackendUrl } from './proxy-state';
import { usageDashboardRoute } from './usage-dashboard';

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
        response_body, response_error_message
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
        ${errorMessage || null}
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

  const cfIp = request.headers.get('CF-Connecting-IP');
  if (cfIp) {
    requestHeaders.set('X-Forwarded-For', cfIp);
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

  app.route('/', usageDashboardRoute);

  app.all('*', async (c) => {
    const env = c.env;
    const request = c.req.raw;
    const requestId = c.get('requestId');
    const requestUrl = new URL(request.url);
    const path = c.req.path || '/';

    if (!env.DATABASE_URL) {
      return c.json(
        { error: 'Proxy not configured', details: 'DATABASE_URL is not set' },
        503,
      );
    }

    const backendUrl = await fetchBackendUrl(env.DATABASE_URL);
    if (!backendUrl) {
      return c.json(
        {
          error: 'Proxy not configured',
          details: 'Set llm_proxy.proxy_state.backend_url',
        },
        503,
      );
    }

    const backendPath = requestUrl.pathname + requestUrl.search;
    const targetUrl = `${backendUrl}${backendPath}`;

    const init: RequestInit = {
      method: request.method,
      headers: buildBackendRequestHeaders(request, requestUrl),
      body: request.body,
    };

    try {
      const response = await fetch(targetUrl, init);
      const responseBody = await readJsonResponseBody(response);

      c.executionCtx.waitUntil(
        logRequest(
          env,
          requestId,
          request.method,
          path,
          requestUrl.searchParams,
          request.headers,
          null,
          response.status,
          response.headers,
          responseBody,
        ),
      );

      console.log(`[${requestId}] ${response.status} ${path}`);

      return new Response(response.body, {
        status: response.status,
        statusText: response.statusText,
        headers: response.headers,
      });
    } catch (error) {
      c.executionCtx.waitUntil(
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

export default createApp();
