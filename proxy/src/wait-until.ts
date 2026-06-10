import type { ExecutionContext } from 'hono';

export function waitUntil(ctx: ExecutionContext | undefined, promise: Promise<unknown>): void {
  if (ctx?.waitUntil) {
    ctx.waitUntil(promise);
  } else {
    void promise.catch((err) => console.error('Background task failed', err));
  }
}

export function createServerExecutionContext(): ExecutionContext {
  return {
    waitUntil(promise) {
      void promise.catch((err) => console.error('Background task failed', err));
    },
    passThroughOnException() {},
    props: {},
  };
}
