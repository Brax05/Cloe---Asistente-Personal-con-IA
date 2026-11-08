#!/usr/bin/env bash
set -eu
cd "$(dirname "$0")"
./start_ollama.sh
.venv/bin/python chat.py "$@"
