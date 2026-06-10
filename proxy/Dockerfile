FROM oven/bun:1-alpine

WORKDIR /app

COPY package.json bun.lock ./
RUN bun install --frozen-lockfile --production

COPY src ./src
COPY public ./public

ENV PORT=8080
EXPOSE 8080

HEALTHCHECK CMD wget -qO- http://localhost:8080/ || exit 1

CMD ["bun", "run", "src/server.ts"]
