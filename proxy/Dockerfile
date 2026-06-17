FROM oven/bun:1-alpine

WORKDIR /app

COPY package.json bun.lock ./
RUN bun install --frozen-lockfile

COPY src ./src
COPY public ./public
COPY vite.config.ts tsconfig.ui.json tsconfig.json ./

RUN bun run build:ui

RUN bun install --frozen-lockfile --production

ENV PORT=8080
EXPOSE 8080

HEALTHCHECK CMD wget -qO- http://localhost:8080/ || exit 1

CMD ["bun", "run", "src/server.ts"]
