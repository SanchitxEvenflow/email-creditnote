#!/usr/bin/env bash
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "==> Installing frontend dependencies..."
cd "$ROOT/frontend"
npm install

echo "==> Building frontend (static export)..."
npm run build

echo "==> Installing backend dependencies..."
cd "$ROOT/backend"
pip install -r requirements.txt

echo "==> Starting backend..."
uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"
