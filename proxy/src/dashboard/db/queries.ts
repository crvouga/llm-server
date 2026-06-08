import { neon } from '@neondatabase/serverless';
import type { DailyUsageRow, RawModelUsageRow } from '../types';
import { todayIsoDate } from '../lib/format';

export async function fetchEarliestUsageDate(databaseUrl: string): Promise<string> {
  const sql = neon(databaseUrl);
  const rows = await sql`
    SELECT COALESCE(MIN(created_at)::date, CURRENT_DATE)::text AS earliest
    FROM llm_proxy.http_log
    WHERE request_path = '/v1/chat/completions'
      AND response_status_code >= 200
      AND response_status_code < 300
      AND response_body ? 'usage'
  `;
  return String(rows[0]?.earliest ?? todayIsoDate());
}

export async function fetchKnownModels(databaseUrl: string): Promise<string[]> {
  const sql = neon(databaseUrl);
  const rows = await sql`
    SELECT DISTINCT COALESCE(request_body->>'model', 'unknown') AS model
    FROM llm_proxy.http_log
    WHERE request_path = '/v1/chat/completions'
    ORDER BY model ASC
  `;

  return rows.map((row) => String(row.model));
}

export async function fetchUsageRows(
  databaseUrl: string,
  startDate: string,
  endDate: string,
): Promise<RawModelUsageRow[]> {
  const sql = neon(databaseUrl);

  const rows = await sql`
    SELECT
      COALESCE(request_body->>'model', 'unknown') AS model,
      COUNT(*)::int AS request_count,
      COALESCE(SUM((response_body->'usage'->>'prompt_tokens')::bigint), 0)::bigint AS prompt_tokens,
      COALESCE(SUM((response_body->'usage'->>'completion_tokens')::bigint), 0)::bigint AS completion_tokens,
      -- Overall TPS: only rows with measured duration (legacy null duration_ms excluded).
      COALESCE(
        SUM((response_body->'usage'->>'completion_tokens')::bigint)
          FILTER (WHERE duration_ms IS NOT NULL AND duration_ms > 0),
        0
      )::bigint AS timed_completion_tokens,
      COALESCE(SUM(duration_ms) FILTER (WHERE duration_ms IS NOT NULL AND duration_ms > 0), 0)::bigint AS total_duration_ms,
      -- Generation TPS: streaming subset where decode window (duration - ttft) is positive.
      COALESCE(
        SUM((response_body->'usage'->>'completion_tokens')::bigint)
          FILTER (WHERE ttft_ms IS NOT NULL AND duration_ms > ttft_ms),
        0
      )::bigint AS generation_completion_tokens,
      COALESCE(
        SUM(duration_ms - ttft_ms) FILTER (WHERE ttft_ms IS NOT NULL AND duration_ms > ttft_ms),
        0
      )::bigint AS total_generation_ms
    FROM llm_proxy.http_log
    WHERE request_path = '/v1/chat/completions'
      AND response_status_code >= 200
      AND response_status_code < 300
      AND response_body ? 'usage'
      AND created_at >= ${startDate}::date
      AND created_at < (${endDate}::date + INTERVAL '1 day')
    GROUP BY 1
    ORDER BY (
      COALESCE(SUM((response_body->'usage'->>'prompt_tokens')::bigint), 0)
      + COALESCE(SUM((response_body->'usage'->>'completion_tokens')::bigint), 0)
    ) DESC
  `;

  return rows.map((row) => ({
    model: String(row.model),
    requestCount: Number(row.request_count),
    promptTokens: Number(row.prompt_tokens),
    completionTokens: Number(row.completion_tokens),
    timedCompletionTokens: Number(row.timed_completion_tokens),
    totalDurationMs: Number(row.total_duration_ms),
    generationCompletionTokens: Number(row.generation_completion_tokens),
    totalGenerationMs: Number(row.total_generation_ms),
  }));
}

export async function fetchDailyUsageRows(
  databaseUrl: string,
  startDate: string,
  endDate: string,
): Promise<DailyUsageRow[]> {
  const sql = neon(databaseUrl);

  const rows = await sql`
    SELECT
      created_at::date::text AS day,
      COALESCE(SUM((response_body->'usage'->>'prompt_tokens')::bigint), 0)::bigint AS prompt_tokens,
      COALESCE(SUM((response_body->'usage'->>'completion_tokens')::bigint), 0)::bigint AS completion_tokens
    FROM llm_proxy.http_log
    WHERE request_path = '/v1/chat/completions'
      AND response_status_code >= 200
      AND response_status_code < 300
      AND response_body ? 'usage'
      AND created_at >= ${startDate}::date
      AND created_at < (${endDate}::date + INTERVAL '1 day')
    GROUP BY 1
    ORDER BY 1 ASC
  `;

  return rows.map((row) => {
    const promptTokens = Number(row.prompt_tokens);
    const completionTokens = Number(row.completion_tokens);
    return {
      day: String(row.day),
      promptTokens,
      completionTokens,
      totalTokens: promptTokens + completionTokens,
    };
  });
}
