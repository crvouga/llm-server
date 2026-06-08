import { neon } from '@neondatabase/serverless';

const databaseUrl = process.env.DATABASE_URL || "postgresql://neondb_owner:npg_5dynuDtLM6kO@ep-fragrant-math-aprmjhvj.c-7.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require";

console.log("Testing database connection...");
console.log("DATABASE_URL:", databaseUrl.substring(0, 40) + "...");

const sql = neon(databaseUrl);

try {
  const result = await sql`SELECT COUNT(*)::int as count FROM llm_proxy.http_log`;
  console.log("SUCCESS! Table exists and has data:");
  console.log(result);
} catch (error) {
  console.error("ERROR:", error.message);
  console.error("Error details:", error);
}
