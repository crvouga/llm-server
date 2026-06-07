#!/bin/bash
# Database setup script for LLM Proxy usage tracking

set -e

echo "Setting up LLM Proxy database..."

if [ -z "$DATABASE_URL" ]; then
  echo "Error: DATABASE_URL environment variable not set"
  exit 1
fi

echo "Connecting to database..."

# Check if table exists and create if not
psql "$DATABASE_URL" -f "$(dirname "$0")/schema.sql"

echo "Database setup complete!"
