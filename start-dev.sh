#!/usr/bin/env bash
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "==> Starting backend on :8000 (with reload)..."
cd "$ROOT/backend"
uvicorn main:app --reload --port 8000 &
BACKEND_PID=$!

echo "==> Starting frontend dev server on :3000..."
cd "$ROOT/frontend"
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev

# Kill backend when frontend exits
kill $BACKEND_PID 2>/dev/null || true
