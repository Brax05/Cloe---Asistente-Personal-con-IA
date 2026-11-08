#!/usr/bin/env bash
set -eu
cd "$(dirname "$0")"

if [ -f "./start_ollama.sh" ]; then
    ./start_ollama.sh || true
fi

exec .venv/bin/python chat.py "$@"
