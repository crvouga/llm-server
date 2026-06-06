import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { neon } from "@neondatabase/serverless";

const databaseUrl = process.env.DATABASE_URL;

if (!databaseUrl) {
  console.error("DATABASE_URL is required");
  process.exit(1);
}

const __dirname = dirname(fileURLToPath(import.meta.url));
const schemaPath = join(__dirname, "..", "sql", "schema.sql");
const schema = readFileSync(schemaPath, "utf8");
const sql = neon(databaseUrl);

for (const statement of schema.split(";")) {
  const trimmed = statement.trim();

  if (!trimmed) {
    continue;
  }

  await sql.query(trimmed);
}

console.log("Applied llm_server schema");
