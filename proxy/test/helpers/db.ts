import { neon } from '@neondatabase/serverless';
import { resetBackendUrlCache } from '../../src/proxy-state';
import type { DailyUsageRow, RawModelUsageRow } from '../../src/dashboard/types';

export function requireDatabaseUrl(): string {
  const url = process.env.DATABASE_URL;
  if (!url) {
    throw new Error(
      'DATABASE_URL is not set. Run tests with: vault run --project personal --config dev -- bun test',
    );
  }
  return url;
}

export function createRunId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function sentinelModel(runId: string, name: string): string {
  return `__test__${runId}-${name}`;
}

export function sqlClient(databaseUrl: string = requireDatabaseUrl()) {
  return neon(databaseUrl);
}

export interface InsertLogRowOptions {
  id?: string;
  createdAt: string;
  model?: string;
  path?: string;
  method?: string;
  statusCode?: number;
  promptTokens?: number;
  completionTokens?: number;
  includeUsage?: boolean;
  requestBody?: object | null;
  responseBody?: object | null;
}

function buildRequestBody(options: InsertLogRowOptions): string | null {
  if (options.requestBody === null) {
    return null;
  }
  if (options.requestBody !== undefined) {
    return JSON.stringify(options.requestBody);
  }
  return JSON.stringify({ model: options.model ?? 'unknown', messages: [] });
}

function buildResponseBody(options: InsertLogRowOptions): string | null {
  if (options.responseBody === null) {
    return null;
  }
  if (options.responseBody !== undefined) {
    return JSON.stringify(options.responseBody);
  }

  const includeUsage = options.includeUsage ?? true;
  if (!includeUsage) {
    return JSON.stringify({ error: 'no usage' });
  }

  const promptTokens = options.promptTokens ?? 0;
  const completionTokens = options.completionTokens ?? 0;
  return JSON.stringify({
    usage: {
      prompt_tokens: promptTokens,
      completion_tokens: completionTokens,
      total_tokens: promptTokens + completionTokens,
    },
  });
}

export async function insertLogRow(options: InsertLogRowOptions): Promise<string> {
  const sql = sqlClient();
  const id = options.id ?? crypto.randomUUID();
  const path = options.path ?? '/v1/chat/completions';
  const method = options.method ?? 'POST';
  const statusCode = options.statusCode ?? 200;
  const requestBody = buildRequestBody(options);
  const responseBody = buildResponseBody(options);

  await sql`
    INSERT INTO llm_proxy.http_log (
      id, created_at, request_method, request_path, request_query_params,
      request_headers, request_body, response_status_code, response_headers,
      response_body, response_error_message
    )
    VALUES (
      ${id}::uuid,
      ${options.createdAt}::timestamptz,
      ${method},
      ${path},
      '{}'::jsonb,
      '{}'::jsonb,
      ${requestBody}::jsonb,
      ${statusCode},
      '{}'::jsonb,
      ${responseBody}::jsonb,
      NULL
    )
  `;

  return id;
}

export async function insertLogRows(optionsList: InsertLogRowOptions[]): Promise<string[]> {
  const ids: string[] = [];
  for (const options of optionsList) {
    ids.push(await insertLogRow(options));
  }
  return ids;
}

export function sumUsageRows(rows: RawModelUsageRow[]): {
  requestCount: number;
  promptTokens: number;
  completionTokens: number;
} {
  return rows.reduce(
    (acc, row) => ({
      requestCount: acc.requestCount + row.requestCount,
      promptTokens: acc.promptTokens + row.promptTokens,
      completionTokens: acc.completionTokens + row.completionTokens,
    }),
    { requestCount: 0, promptTokens: 0, completionTokens: 0 },
  );
}

export function sumDailyRows(rows: DailyUsageRow[]): {
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
} {
  return rows.reduce(
    (acc, row) => ({
      promptTokens: acc.promptTokens + row.promptTokens,
      completionTokens: acc.completionTokens + row.completionTokens,
      totalTokens: acc.totalTokens + row.totalTokens,
    }),
    { promptTokens: 0, completionTokens: 0, totalTokens: 0 },
  );
}

export async function cleanupTestRows(runId: string, extraIds: string[] = []): Promise<void> {
  const sql = sqlClient();
  const pattern = `__test__${runId}%`;
  await sql`
    DELETE FROM llm_proxy.http_log
    WHERE request_body->>'model' LIKE ${pattern}
  `;

  for (const id of extraIds) {
    await sql`
      DELETE FROM llm_proxy.http_log
      WHERE id = ${id}::uuid
    `;
  }
}

export async function getBackendUrl(): Promise<string | null> {
  const sql = sqlClient();
  const rows = await sql`
    SELECT backend_url
    FROM llm_proxy.config
    WHERE id = 1
    LIMIT 1
  `;
  if (rows.length === 0) {
    return null;
  }
  return String(rows[0].backend_url ?? '');
}

export async function setBackendUrl(url: string): Promise<void> {
  resetBackendUrlCache();
  const sql = sqlClient();
  await sql`
    INSERT INTO llm_proxy.config (id, backend_url, updated_at)
    VALUES (1, ${url}, NOW())
    ON CONFLICT (id) DO UPDATE
    SET backend_url = EXCLUDED.backend_url,
        updated_at = NOW()
  `;
}

export async function fetchLogRowById(id: string) {
  const sql = sqlClient();
  const rows = await sql`
    SELECT
      id,
      request_path,
      request_body,
      response_status_code,
      response_body,
      response_error_message
    FROM llm_proxy.http_log
    WHERE id = ${id}::uuid
    LIMIT 1
  `;
  return rows[0] ?? null;
}

export async function fetchLatestLogRowByPath(path: string) {
  const sql = sqlClient();
  const rows = await sql`
    SELECT id, request_path, request_body, response_status_code, response_body, response_error_message
    FROM llm_proxy.http_log
    WHERE request_path = ${path}
    ORDER BY created_at DESC
    LIMIT 1
  `;
  return rows[0] ?? null;
}

export async function fetchLatestLogRowByModel(model: string) {
  const sql = sqlClient();
  const rows = await sql`
    SELECT
      id,
      request_path,
      request_body,
      response_status_code,
      response_body,
      response_error_message
    FROM llm_proxy.http_log
    WHERE request_body->>'model' = ${model}
    ORDER BY created_at DESC
    LIMIT 1
  `;
  return rows[0] ?? null;
}

export async function todayIsoDate(): Promise<string> {
  const sql = sqlClient();
  const rows = await sql`SELECT CURRENT_DATE::text AS today`;
  return String(rows[0]?.today);
}
