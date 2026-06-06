import { createDb } from "./db";
import type { StreamResponseLog } from "../types/openai";

export interface Env {
  LM_STUDIO_URL: string;
  DATABASE_URL: string;
}

const TRACKED_ENDPOINTS = new Set([
  "/v1/chat/completions",
  "/v1/completions",
  "/v1/embeddings",
]);

const HOP_BY_HOP_HEADERS = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailers",
  "transfer-encoding",
  "upgrade",
  "host",
]);

export default {
  async fetch(
    request: Request,
    env: Env,
    ctx: ExecutionContext,
  ): Promise<Response> {
    const pathname = new URL(request.url).pathname;
    const shouldTrack =
      request.method === "POST" && TRACKED_ENDPOINTS.has(pathname);

    let reqPayload: unknown = null;

    if (shouldTrack) {
      try {
        reqPayload = await request.clone().json();
      } catch (error) {
        console.error("Failed to parse request body for logging", error);
      }
    }

    const upstreamUrl = buildUpstreamUrl(env.LM_STUDIO_URL, request.url);
    const upstreamRequest = new Request(upstreamUrl, {
      method: request.method,
      headers: proxyHeaders(request.headers),
      body: request.body,
      redirect: "manual",
    });

    const response = await fetch(upstreamRequest);

    if (!shouldTrack || !response.ok || reqPayload === null) {
      return response;
    }

    const apiKeyHash = await hashAuthorizationHeader(
      request.headers.get("authorization"),
    );
    const contentType = response.headers.get("content-type") ?? "";

    if (contentType.includes("text/event-stream")) {
      return trackStreamingResponse(
        response,
        pathname,
        env,
        ctx,
        apiKeyHash,
        reqPayload,
      );
    }

    if (contentType.includes("application/json")) {
      return trackJsonResponse(
        response,
        pathname,
        env,
        ctx,
        apiKeyHash,
        reqPayload,
      );
    }

    return response;
  },
};

function buildUpstreamUrl(baseUrl: string, requestUrl: string): string {
  const incoming = new URL(requestUrl);
  const upstream = new URL(baseUrl);
  upstream.pathname = incoming.pathname;
  upstream.search = incoming.search;
  return upstream.toString();
}

function proxyHeaders(headers: Headers): Headers {
  const proxied = new Headers();

  headers.forEach((value, key) => {
    if (!HOP_BY_HOP_HEADERS.has(key.toLowerCase())) {
      proxied.set(key, value);
    }
  });

  return proxied;
}

async function hashAuthorizationHeader(
  authorization: string | null,
): Promise<string | null> {
  if (!authorization) {
    return null;
  }

  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(authorization),
  );

  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

async function trackJsonResponse(
  response: Response,
  endpoint: string,
  env: Env,
  ctx: ExecutionContext,
  apiKeyHash: string | null,
  reqPayload: unknown,
): Promise<Response> {
  const cloned = response.clone();

  ctx.waitUntil(
    (async () => {
      try {
        const payload = await cloned.json();
        const db = createDb(env.DATABASE_URL);

        await db.logUsage({
          endpoint,
          apiKeyHash,
          req: reqPayload,
          res: payload,
        });
      } catch (error) {
        console.error("Failed to log JSON usage", error);
      }
    })(),
  );

  return response;
}

function trackStreamingResponse(
  response: Response,
  endpoint: string,
  env: Env,
  ctx: ExecutionContext,
  apiKeyHash: string | null,
  reqPayload: unknown,
): Response {
  if (!response.body) {
    return response;
  }

  const decoder = new TextDecoder();
  let sseBuffer = "";

  const transform = new TransformStream<Uint8Array, Uint8Array>({
    transform(chunk, controller) {
      controller.enqueue(chunk);
      sseBuffer += decoder.decode(chunk, { stream: true });
    },
    flush() {
      ctx.waitUntil(
        (async () => {
          try {
            const chunks = parseSseChunks(sseBuffer);
            const streamResponse: StreamResponseLog = {
              stream: true,
              chunks,
            };
            const db = createDb(env.DATABASE_URL);

            await db.logUsage({
              endpoint,
              apiKeyHash,
              req: reqPayload,
              res: streamResponse,
            });
          } catch (error) {
            console.error("Failed to log streaming usage", error);
          }
        })(),
      );
    },
  });

  const headers = new Headers(response.headers);
  headers.delete("content-length");

  return new Response(response.body.pipeThrough(transform), {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

function parseSseChunks(payload: string): unknown[] {
  const chunks: unknown[] = [];

  for (const line of payload.split("\n")) {
    if (!line.startsWith("data: ")) {
      continue;
    }

    const data = line.slice(6).trim();

    if (!data || data === "[DONE]") {
      continue;
    }

    try {
      chunks.push(JSON.parse(data));
    } catch {
      continue;
    }
  }

  return chunks;
}
