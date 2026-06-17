/** Ensure llm_proxy.config.backend_url points at the public LLM API. */

import { neon } from '@neondatabase/serverless';
import { DEFAULT_BACKEND_URL } from '../src/proxy-state';

function isLoopbackBackend(url: string): boolean {
  try {
    const host = new URL(url).hostname;
    return host === '127.0.0.1' || host === 'localhost' || host === '::1';
  } catch {
    return false;
  }
}

async function main(): Promise<void> {
  const databaseUrl = process.env.DATABASE_URL;
  if (!databaseUrl) {
    console.error('DATABASE_URL is not set');
    process.exit(1);
  }

  const sql = neon(databaseUrl);
  const rows = await sql`
    SELECT backend_url
    FROM llm_proxy.config
    WHERE id = 1
    LIMIT 1
  `;

  const current = rows.length > 0 ? String(rows[0].backend_url ?? '') : '';
  if (current && !isLoopbackBackend(current)) {
    console.log(`backend_url ok: ${current}`);
    return;
  }

  await sql`
    INSERT INTO llm_proxy.config (id, backend_url, updated_at)
    VALUES (1, ${DEFAULT_BACKEND_URL}, NOW())
    ON CONFLICT (id) DO UPDATE SET
      backend_url = EXCLUDED.backend_url,
      updated_at = EXCLUDED.updated_at
  `;

  console.log(`backend_url set to ${DEFAULT_BACKEND_URL}`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
