#!/usr/bin/env bash
# Start a local AnsiBlaster for manual testing: bundled example/ roles + playbooks, with its
# database and run artifacts kept in a throwaway .dev-data/ directory (gitignored) so it never
# touches real data. Runs in the foreground; Ctrl+C stops it.
#
# Usage: scripts/dev-server.sh [--reload]
#   PORT=9000 scripts/dev-server.sh     # default 8000
#   --reload                            # auto-reload on code changes (uvicorn dev server)
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

# uv's installer puts it in ~/.local/bin, which a non-login shell may not have on PATH.
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found. Install it: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

export ANSIBLASTER_DIR="${ANSIBLASTER_DIR:-$repo_root/.dev-data}"
export ANSIBLASTER_ANSIBLE__PATH="${ANSIBLASTER_ANSIBLE__PATH:-$repo_root/example}"
export ANSIBLASTER_SERVER__PORT="${PORT:-${ANSIBLASTER_SERVER__PORT:-8000}}"

uv sync --quiet

echo "AnsiBlaster dev server: http://localhost:${ANSIBLASTER_SERVER__PORT}"
echo "  content: $ANSIBLASTER_ANSIBLE__PATH"
echo "  data:    $ANSIBLASTER_DIR"

if [[ "${1:-}" == "--reload" ]]; then
  exec uv run uvicorn ansiblaster.app:app --reload \
    --host "${ANSIBLASTER_SERVER__HOST:-0.0.0.0}" --port "$ANSIBLASTER_SERVER__PORT"
fi
exec uv run ansiblaster
