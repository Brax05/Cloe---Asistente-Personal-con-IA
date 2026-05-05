import re
import sys
import os
import json
import logging
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=True)

# Silenciar los errores HTTP de spotipy en la terminal
logging.getLogger("spotipy").setLevel(logging.CRITICAL)
logging.getLogger("urllib3").setLevel(logging.CRITICAL)

import ollama
from services.spotify_tools import create_client, get_playlist_tracks, format_playlist_context, play_track
from services.google_auth import get_google_credentials
from services.calendar_tools import get_calendar_service
from services.gmail_tools import get_gmail_service
from tools import ToolDispatcher, available_tool_names

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
MODEL = "cloe"

MUSIC_PATTERN = re.compile(r'♪\s*([^♪\n\-]+?)\s*-\s*([^♪\n\[]+)')

_MUSIC_KEYWORDS = {
    "música", "musica", "canción", "cancion", "song", "songs",
    "reproduce", "pon ", "escuchar", "escucha", "playlist",
    "spotify", "artista", "album", "álbum", "recomienda",
    "recomendación", "recomendacion", "suena", "sonando",
    "poner", "quiero escuchar", "pon algo", "siguiente", "pausa",
}

def detect_songs(text: str) -> list[tuple[str, str]]:
    return [(m.group(1).strip(), m.group(2).strip()) for m in MUSIC_PATTERN.finditer(text)]

def is_music_context(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in _MUSIC_KEYWORDS)


def extract_inline_tool_calls(text: str) -> tuple[str, list[tuple[str, dict]]]:
    """
    El Modelfile de Cloe genera tool calls como texto plano JSON:
      {"name": "spotify_play", "parameters": {"query": "algo"}}
    Esta función los detecta y devuelve el texto limpio + lista de (nombre, args).
    """
    calls: list[tuple[str, dict]] = []
    clean = text
    i = 0
    while i < len(text):
        if text[i] != "{":
            i += 1
            continue
        depth = 0
        for j in range(i, len(text)):
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    fragment = text[i:j + 1]
                    try:
                        obj = json.loads(fragment)
                        if isinstance(obj, dict) and "name" in obj:
                            name = obj["name"]
                            args = obj.get("parameters") or obj.get("arguments") or {}
                            if isinstance(args, dict):
                                calls.append((name, args))
                                clean = clean.replace(fragment, "", 1)
                    except (json.JSONDecodeError, ValueError):
                        pass
                    break
        i += 1
    return clean.strip(), calls


def get_modelfile_system(client: ollama.Client) -> str:
    """Lee el system prompt del Modelfile de Cloe para no sobreescribir su personalidad."""
    try:
        info = client.show(MODEL)
        # Versiones nuevas del SDK exponen .system directamente
        system = getattr(info, "system", None)
        if system:
            return system.strip()
        # Fallback: parsear el Modelfile
        modelfile = getattr(info, "modelfile", "") or ""
        match = re.search(r'SYSTEM\s+"""(.*?)"""', modelfile, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        match = re.search(r'SYSTEM\s+"(.*?)"', modelfile, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
    except Exception:
        pass
    return ""


def build_tool_hints(services: dict) -> str:
    """Instrucciones mínimas de herramientas que se añaden al system del Modelfile."""
    parts = [
        "## REGLA ABSOLUTA DE HERRAMIENTAS",
        "NUNCA llames ninguna herramienta de forma automática durante una conversación normal.",
        "Solo llama una herramienta cuando el usuario lo pida de forma EXPLÍCITA y DIRECTA.",
        "Si una herramienta falla, NO la vuelvas a llamar en ese mismo turno ni en los siguientes.",
        "",
    ]

    if services.get("spotify"):
        parts += [
            "## Herramientas — Spotify (solo bajo pedido explícito)",
            "- spotify_play: solo si el usuario dice 'pon', 'reproduce', 'quiero escuchar' + nombre de canción/artista.",
            "- spotify_pause: solo si el usuario dice 'pausa' o 'para la música'.",
            "- spotify_next / spotify_previous: solo si el usuario dice 'siguiente' o 'anterior'.",
            "- spotify_volume: solo si el usuario pide cambiar el volumen.",
            "- spotify_now_playing: solo si el usuario pregunta '¿qué está sonando?'.",
            "- spotify_recommendations: solo si el usuario dice explícitamente 'recomiéndame música'.",
            "- En cualquier otro caso NO uses herramientas de Spotify.",
        ]

    if services.get("calendar"):
        parts += [
            "",
            "## Herramientas — Calendario",
            "- calendar_today: solo al saludo inicial O si el usuario pregunta por su agenda.",
            "- calendar_upcoming: solo si el usuario pregunta qué tiene próximamente.",
            "- calendar_create: solo si el usuario quiere crear un evento.",
        ]

    if services.get("gmail"):
        parts += [
            "",
            "## Herramientas — Gmail",
            "- gmail_unread: solo al saludo inicial O si el usuario pregunta por correos.",
            "- gmail_send: solo si el usuario quiere enviar un correo.",
        ]

    return "\n".join(parts)


def connect_services() -> dict:
    services = {}

    print("Conectando con Spotify...")
    try:
        sp = create_client()
        playlist_id = os.getenv("SPOTIFY_PLAYLIST_ID", "")
        if playlist_id:
            tracks = get_playlist_tracks(sp, playlist_id)
            print(f"  ✓ Playlist cargada: {len(tracks)} canciones")
        else:
            tracks = []
            print("  ✓ Spotify conectado")
        services["spotify"] = sp
        services["spotify_tracks"] = tracks
    except Exception as e:
        print(f"  ✗ Spotify no disponible: {e}")
        services["spotify"] = None
        services["spotify_tracks"] = []

    print("Conectando con Google...")
    try:
        creds = get_google_credentials()
        services["calendar"] = get_calendar_service(creds)
        services["gmail"] = get_gmail_service(creds)
        print("  ✓ Calendar y Gmail conectados")
    except FileNotFoundError as e:
        print(f"  ✗ Google no configurado:\n    {e}")
        services["calendar"] = None
        services["gmail"] = None
    except Exception as e:
        print(f"  ✗ Google no disponible: {e}")
        services["calendar"] = None
        services["gmail"] = None

    return services


def run_tool_loop(client, messages: list, tools: list, dispatcher: ToolDispatcher) -> str:
    """
    Soporta dos modos de tool calling:
    1. API nativa (response.message.tool_calls) — modelos con soporte estándar
    2. Texto inline JSON — formato del Modelfile de Cloe
    """
    response = client.chat(model=MODEL, messages=messages, tools=tools)
    reply_msg = response.message

    for _ in range(6):  # máximo 6 iteraciones para evitar loops infinitos
        content = reply_msg.content or ""
        api_calls = getattr(reply_msg, "tool_calls", None) or []

        # Detectar tool calls en texto (formato del Modelfile de Cloe)
        clean_content, text_calls = extract_inline_tool_calls(content)

        if not api_calls and not text_calls:
            break  # Sin tool calls: respuesta final

        # Procesar API tool calls
        if api_calls:
            messages.append({
                "role": "assistant",
                "content": clean_content,
                "tool_calls": api_calls,
            })
            for tc in api_calls:
                name = tc.function.name
                args = tc.function.arguments or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                if isinstance(args, dict):
                    args = {k: v for k, v in args.items()
                            if isinstance(k, str) and k.isidentifier() and v not in (None, "", [])}
                print(f"  ⚙  {name}({', '.join(f'{k}={v}' for k, v in args.items())})")
                messages.append({"role": "tool", "content": dispatcher.run(name, args)})

        # Procesar text-based tool calls (Cloe Modelfile)
        if text_calls and not api_calls:
            messages.append({"role": "assistant", "content": clean_content})
            for name, args in text_calls:
                if isinstance(args, dict):
                    args = {k: v for k, v in args.items()
                            if isinstance(k, str) and k.isidentifier() and v not in (None, "", [])}
                print(f"  ⚙  {name}({', '.join(f'{k}={v}' for k, v in args.items())})")
                messages.append({"role": "tool", "content": dispatcher.run(name, args)})

        response = client.chat(model=MODEL, messages=messages, tools=tools)
        reply_msg = response.message

    return reply_msg.content or ""


def main():
    print("\n╭─────────────────────────────────╮")
    print("│   Iniciando Cloe  (=^◡^=)       │")
    print("╰─────────────────────────────────╯\n")

    services = connect_services()
    dispatcher = ToolDispatcher(services)
    tools = available_tool_names(services)
    tools_enabled = len(tools) > 0

    client = ollama.Client(host=OLLAMA_HOST)

    # Leer el system prompt del Modelfile para preservar la personalidad de Cloe
    modelfile_system = get_modelfile_system(client)
    tool_hints = build_tool_hints(services)

    if modelfile_system and tool_hints:
        system_content = modelfile_system + "\n\n" + tool_hints
    elif tool_hints:
        system_content = tool_hints
    else:
        system_content = modelfile_system

    messages: list[dict] = []
    if system_content:
        messages.append({"role": "system", "content": system_content})

    active = [s for s in ["Spotify", "Calendar", "Gmail"]
              if services.get(s.lower())]
    print(f"\nServicios activos: {', '.join(active) if active else 'ninguno'}")
    print("Escribe 'salir' para salir.\n")
    print("─" * 35)

    # Saludo inicial: solo revisa calendario/gmail, NO Spotify automáticamente
    if tools_enabled:
        from datetime import datetime
        hora = datetime.now().strftime("%H:%M")
        has_google = services.get("calendar") or services.get("gmail")
        trigger = f"Son las {hora}. "
        if has_google:
            trigger += "Revisa el calendario de hoy y los correos importantes. "
        trigger += "Saluda al usuario de forma cálida y breve con lo que encontraste. No hagas listas largas."

        messages.append({"role": "user", "content": trigger})
        print("\nCloe: ", end="", flush=True)
        greeting = run_tool_loop(client, messages, tools, dispatcher)
        messages.append({"role": "assistant", "content": greeting})
        print(greeting)
        print()

    while True:
        try:
            user_input = input("\nTú: ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("salir", "exit", "quit"):
                print("\n(=^-ω-^=)ノ ¡hasta luego!")
                break

            messages.append({"role": "user", "content": user_input})

            if tools_enabled:
                reply = run_tool_loop(client, messages, tools, dispatcher)
            else:
                response = client.chat(model=MODEL, messages=messages)
                reply = response.message.content or ""

            messages.append({"role": "assistant", "content": reply})
            print(f"\nCloe: {reply}")

            # Abre Spotify solo si el contexto era musical
            if services.get("spotify") and is_music_context(user_input):
                for song, artist in detect_songs(reply):
                    result = play_track(services["spotify"], f"{song} {artist}")
                    if result and result.get("method") == "browser_search":
                        print(f"  🎵 Abriendo en Spotify: {song} — {artist}")

        except KeyboardInterrupt:
            print("\n\n(=^-ω-^=)ノ ¡hasta luego!")
            break
        except Exception as e:
            print(f"\nError: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
