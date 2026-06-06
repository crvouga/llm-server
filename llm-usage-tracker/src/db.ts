import { neon } from "@neondatabase/serverless";

export interface UsageLogEntry {
  endpoint: string;
  apiKeyHash: string | null;
  req: unknown;
  res: unknown;
}

export function createDb(databaseUrl: string) {
  const sql = neon(databaseUrl);

  return {
    async logUsage(entry: UsageLogEntry): Promise<void> {
      await sql`
        INSERT INTO llm_server.usage_logs (
          endpoint,
          api_key_hash,
          req,
          res
        ) VALUES (
          ${entry.endpoint},
          ${entry.apiKeyHash},
          ${entry.req},
          ${entry.res}
        )
      `;
    },
  };
}
