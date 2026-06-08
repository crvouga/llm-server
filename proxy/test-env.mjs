// Test what env variables are available
console.log("Environment check:");
console.log("DATABASE_URL from .dev.vars:", process.env.DATABASE_URL?.substring(0, 50) + "...");
