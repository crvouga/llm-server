/** Collects waitUntil promises so tests can await async logging before DB assertions. */

import type { ExecutionContext } from 'hono';

export interface TestExecutionContext {
  ctx: ExecutionContext;
  drain: () => Promise<void>;
}

export function createTestCtx(): TestExecutionContext {
  const pending: Promise<unknown>[] = [];

  const ctx: ExecutionContext = {
    waitUntil(promise: Promise<unknown>) {
      pending.push(promise);
    },
    passThroughOnException() {
      // no-op for tests
    },
    props: {},
  };

  return {
    ctx,
    async drain() {
      await Promise.all(pending);
    },
  };
}
