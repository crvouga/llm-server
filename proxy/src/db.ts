// Shared PostgreSQL client. Uses Bun's built-in driver over the standard wire protocol, so it works
// with any Postgres (PlanetScale, Neon, local) rather than only Neon's HTTP endpoint.
//
// JSON parameters: Bun encodes a string bound to `::jsonb` as a JSON *string scalar*. Pass
// JSON.stringify output as `${text}::text::jsonb` so it is parsed into a real object/array.

import { SQL } from 'bun';

const clients = new Map<string, SQL>();

export function sqlClient(databaseUrl: string): SQL {
  let client = clients.get(databaseUrl);
  if (!client) {
    client = new SQL({ url: databaseUrl, max: 4, idleTimeout: 30, connectionTimeout: 10 });
    clients.set(databaseUrl, client);
  }
  return client;
}

/** Short, secret-free error identifier for logs (SQLSTATE, errno or 'unknown'). */
export function dbErrorCode(error: unknown): string {
  if (typeof error === 'object' && error !== null) {
    const { code, errno } = error as { code?: unknown; errno?: unknown };
    if (typeof code === 'string' && code) return code;
    if (typeof errno === 'string' && errno) return errno;
  }
  return 'unknown';
}
