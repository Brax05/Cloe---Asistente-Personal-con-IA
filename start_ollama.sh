#!/usr/bin/env bash
# Arranca el servidor de Ollama si no está corriendo ya.
set -eu
OLLAMA_BIN="${HOME}/.local/bin/ollama"
if [ ! -x "$OLLAMA_BIN" ]; then
    OLLAMA_BIN="$(command -v ollama || true)"
fi
if [ -z "$OLLAMA_BIN" ]; then
    echo "Ollama no está instalado. Instálalo en ~/.local/ollama o en PATH." >&2
    exit 1
fi
if curl -s http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    echo "Ollama ya está corriendo."
else
    echo "Arrancando Ollama..."
    nohup "$OLLAMA_BIN" serve >/tmp/opencode/ollama.log 2>&1 &
    for i in $(seq 1 30); do
        curl -s http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && break
        sleep 1
    done
    if ! curl -s http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
        echo "No se pudo arrancar Ollama. Revisa /tmp/opencode/ollama.log" >&2
        exit 1
    fi
    echo "Ollama listo."
fi
