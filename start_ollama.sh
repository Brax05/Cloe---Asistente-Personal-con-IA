#!/usr/bin/env bash
# Arranca el servidor de Ollama si no está corriendo ya.
set -eu

OLLAMA_BIN="${HOME}/.local/bin/ollama"
if [ ! -x "$OLLAMA_BIN" ]; then
    OLLAMA_BIN="$(command -v ollama || true)"
fi

if [ -z "$OLLAMA_BIN" ] || [ ! -x "$OLLAMA_BIN" ]; then
    echo "Ollama no está instalado (opcional si usas Groq o Gemini)."
    exit 0
fi

if curl -s http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    echo "Ollama ya está corriendo."
    exit 0
fi

echo "Arrancando Ollama..."
LOG_DIR="${TMPDIR:-/tmp}/cloe"
mkdir -p "$LOG_DIR"
nohup "$OLLAMA_BIN" serve >"$LOG_DIR/ollama.log" 2>&1 &

for i in $(seq 1 10); do
    if curl -s http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
        echo "Ollama listo."
        exit 0
    fi
    sleep 1
done

echo "Aviso: Ollama no respondió en 10s (revisa $LOG_DIR/ollama.log). Continuando con Cloe..."
exit 0
