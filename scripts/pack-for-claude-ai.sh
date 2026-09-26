#!/usr/bin/env bash
# Pack wikipedia-trends for claude.ai upload (no symlinks, no .venv).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SKILL_DIR="$ROOT/wikipedia-trends"
OUT="${1:-$ROOT/wikipedia-trends-skill-claude-ai.zip}"
STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT

rsync -a \
  --exclude '.venv' \
  --exclude 'data' \
  --exclude 'reports' \
  --exclude '__pycache__' \
  --exclude '.DS_Store' \
  --exclude '*.pyc' \
  "$SKILL_DIR/" "$STAGING/wikipedia-trends/"

if find "$STAGING/wikipedia-trends" -type l | grep -q .; then
  echo "ERROR: symlinks in staging (claude.ai rejects them)" >&2
  find "$STAGING/wikipedia-trends" -type l >&2
  exit 1
fi

(cd "$STAGING" && zip -qr "$OUT" wikipedia-trends)
echo "Wrote $OUT ($(du -h "$OUT" | cut -f1)) — upload this zip in claude.ai Skills settings."
