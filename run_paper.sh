#!/usr/bin/env bash
# Paper-trade the SPCX ORB agent. Safe by default: this NEVER trades live.
#
# Usage:
#   1. cp .env.example .env  and put your Alpaca *paper* keys in it
#   2. ./run_paper.sh
#
# Run it a few minutes before the 09:30 ET open and leave it up; it polls
# through the session and force-flattens before the close.
set -euo pipefail
cd "$(dirname "$0")"

# Force paper mode regardless of what's in the environment/.env.
export LUCK_MODE=paper

if [ ! -f .env ]; then
  echo "No .env found. Run: cp .env.example .env  then add your Alpaca paper keys." >&2
  exit 1
fi

# Preflight: confirm deps are importable before market open.
python3 -c "import alpaca, yaml, dotenv" 2>/dev/null || {
  echo "Installing dependencies..." >&2
  pip3 install -q -r requirements.txt
}

echo "Starting SPCX agent in PAPER mode. Ctrl-C to stop (it will flatten first)."
exec python3 -m luck.main "$@"
