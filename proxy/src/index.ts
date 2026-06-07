// Transparent LLM Proxy with Raw Request Logging
// Forwards all requests to LM Studio and logs raw request/response data to PostgreSQL

import { neon, NeonDbError } from '@neondatabase/serverless';

import { handleUsageDashboard, isUsageDashboardPath } from './usage-dashboard';

export interface Env {
  DATABASE_URL: string;
  BACKEND_URL?: string;
}

const DEFAULT_BACKEND = 'https://lm-studio.chrisvouga.dev';

// Generate a unique request ID for correlation (Neon uses gen_random_uuid)
function generateRequestId(): string {
  // Use crypto.randomUUID if available, otherwise fallback
  try {
    return crypto.randomUUID();
  } catch {
    // Fallback: timestamp + random chars
    const chars = '0123456789abcdef';
    let id = Date.now().toString(16);
    for (let i = 0; i < 12; i++) {
      id += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    return id;
  }
}

// Convert Headers to plain object
function headersToObject(headers: Headers): Record<string, string> {
  const obj: Record<string, string> = {};
  headers.forEach((value, key) => {
    obj[key] = value;
  });
  return obj;
}

// Store raw request/response data in PostgreSQL (Neon compatible)
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

    // Convert query params to object using forEach
    const queryParamsObj: Record<string, string> = {};
    query.forEach((value, key) => {
      queryParamsObj[key] = value;
    });

    // Tagged-template interpolation: the driver parameterizes each ${value}
    // so it is sent separately from the SQL text (injection-safe, and the
    // password-bearing connection string is never part of the query).
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
    // Non-blocking: don't fail the request if logging fails.
    // NEVER log the error message or object — driver errors (and Workers'
    // "Fetch API cannot load: <url>" TypeError) embed the DATABASE_URL
    // (with password) in the message. Only emit the Postgres error code.
    const code = error instanceof NeonDbError ? error.code : 'unknown';
    console.error(`Request logging failed (code: ${code ?? 'unknown'})`);
  }
}

// Extract endpoint path from request URL
function getPath(url: URL): string {
  return url.pathname || '/';
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const backendUrl = env.BACKEND_URL || DEFAULT_BACKEND;

    // Parse incoming request
    const requestUrl = new URL(request.url);
    const path = getPath(requestUrl);
    const requestId = generateRequestId();

    console.log(`[${requestId}] ${request.method} ${path}`);

    if (isUsageDashboardPath(path)) {
      return handleUsageDashboard(request, env);
    }

    // Construct backend URL
    const backendPath = requestUrl.pathname + requestUrl.search;
    const targetUrl = `${backendUrl}${backendPath}`;

    // Build headers (exclude host, add forwarding info)
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

    // Forward the request transparently
    const init: RequestInit = {
      method: request.method,
      headers: requestHeaders,
      body: request.body,
    };

    let response: Response;
    try {
      response = await fetch(targetUrl, init);
    } catch (error) {
      // Log the error and return 503
      ctx.waitUntil(
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

      return new Response(
        JSON.stringify({ error: 'Backend unavailable', details: String(error) }),
        { status: 503 },
      );
    }

    // Read response body for logging
    let responseBody: unknown = null;
    const contentType = response.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
      try {
        responseBody = await response.clone().json();
      } catch {
        // Response body is not JSON, skip parsing
      }
    }

    // Log the request/response (use waitUntil so the promise survives
    // after the response is returned — `void` alone drops it in Workers)
    ctx.waitUntil(
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
        undefined,
      ),
    );

    console.log(`[${requestId}] ${response.status} ${path}`);

    // Forward the response transparently
    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: response.headers,
    });
  },
};
