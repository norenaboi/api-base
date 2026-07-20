#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -x .venv/bin/api-base ]]; then
  printf 'API Base is not installed yet. Run ./setup.sh first.\n' >&2
  exit 1
fi

mkdir -p data
export API_BASE_DATABASE="${API_BASE_DATABASE:-$PWD/data/vault.sqlite3}"
export API_BASE_PORT="${API_BASE_PORT:-8766}"

printf 'Open http://127.0.0.1:%s in your browser.\n' "$API_BASE_PORT"
exec .venv/bin/api-base
