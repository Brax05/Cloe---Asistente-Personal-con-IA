import re
import sys
import os
import json
import atexit
import argparse
import logging
import urllib.parse
import urllib.request
import urllib.error
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
from services.memory_tools import extract_and_store_user_memory, format_memory_for_system
from services.vision_clipboard_tools import is_clipboard_request, read_clipboard_text
from services.pc_control_tools import handle_pc_control_intent
from services.web_weather_tools import handle_web_or_weather_intent
from services.terminal_tools import handle_terminal_intent
from tools import ToolDispatcher, available_tool_names

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
MODEL = "cloe"

MUSIC_PATTERN = re.compile(r'(?:^|\n|\s)♪\s+([^♪\n\-~]{2,60}?)\s*-\s*([^♪\n\[\(~]{2,60})')

_MUSIC_KEYWORDS = {
    "música", "musica", "canción", "cancion", "canciones", "song", "songs",
    "reproduce", "pon ", "escuchar", "escucha", "playlist",
    "spotify", "artista", "album", "álbum", "recomienda música", "recomiendame musica",
    "recomiéndame música", "recomienda canciones", "recomiéndame canciones",
    "michi-música", "michi-musica", "suena", "sonando",
    "poner música", "poner musica", "quiero escuchar", "pon algo", "siguiente", "pausa",
}

_TOOL_TRIGGER_KEYWORDS = _MUSIC_KEYWORDS | {
    "calendario", "agenda", "evento", "eventos", "reunión", "reunion", "cita", "recordatorio",
    "correo", "correos", "gmail", "email", "mail", "bandeja", "mensaje",
    "llama", "llamar", "llamada", "teléfono", "telefono", "volumen",
}


def detect_songs(text: str) -> list[tuple[str, str]]:
    return [(m.group(1).strip(), m.group(2).strip()) for m in MUSIC_PATTERN.finditer(text)]


def is_music_context(text: str) -> bool:
    lower = (text or "").lower()
    return any(kw in lower for kw in _MUSIC_KEYWORDS)


def should_expose_tools(user_text: str) -> bool:
    """Solo expone herramientas al LLM cuando el mensaje del usuario pide música, agenda, correo o llamadas."""
    lower = (user_text or "").lower()
    return any(kw in lower for kw in _TOOL_TRIGGER_KEYWORDS)


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


def save_env_var(key: str, value: str) -> None:
    """Guarda o actualiza una variable en .env y en os.environ en caliente."""
    os.environ[key] = value
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    lines: list[str] = []
    found = False
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as fh:
            for line in fh:
                if re.match(rf"^\s*#?\s*{re.escape(key)}\s*=", line):
                    if not found:
                        lines.append(f"{key}={value}\n")
                        found = True
                else:
                    lines.append(line)
    if not found:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(f"{key}={value}\n")
    with open(env_path, "w", encoding="utf-8") as fh:
        fh.writelines(lines)


def get_active_llm_info() -> tuple[str, str]:
    """Devuelve (provider, model_name) activos según configuración y API keys disponibles."""
    pref = os.getenv("CLOE_LLM_PROVIDER", "auto").strip().lower()
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    groq_model = os.getenv("CLOE_GROQ_MODEL", "llama-3.3-70b-versatile").strip() or "llama-3.3-70b-versatile"
    gemini_model = os.getenv("CLOE_GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
    ollama_model = os.getenv("CLOE_OLLAMA_MODEL", MODEL).strip() or MODEL

    if pref == "groq" and groq_key:
        return "groq", groq_model
    if pref == "gemini" and gemini_key:
        return "gemini", gemini_model
    if pref == "ollama":
        return "ollama", ollama_model

    # Modo auto: prioriza nube gratuita (0% GPU local) si hay API key configurada
    if groq_key:
        return "groq", groq_model
    if gemini_key:
        return "gemini", gemini_model
    return "ollama", ollama_model


def unload_ollama_vram(client: ollama.Client | None = None) -> None:
    """Libera el modelo local de Ollama de la VRAM/RAM cuando se pasa a un proveedor en la nube."""
    try:
        c = client or ollama.Client(host=OLLAMA_HOST)
        ollama_model = os.getenv("CLOE_OLLAMA_MODEL", MODEL).strip() or MODEL
        c.chat(model=ollama_model, messages=[], keep_alive=0)
    except Exception:
        pass


def get_modelfile_system(client: ollama.Client | None = None) -> str:
    """Lee el system prompt del Modelfile de Cloe (desde archivo local o desde Ollama)."""
    raw = ""
    # 1. Leer primero desde el archivo Modelfile del proyecto (no requiere que Ollama esté en VRAM)
    modelfile_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Modelfile")
    if os.path.exists(modelfile_path):
        try:
            with open(modelfile_path, "r", encoding="utf-8") as fh:
                mf_txt = fh.read()
            match = re.search(r'SYSTEM\s+"""(.*?)"""', mf_txt, re.DOTALL | re.IGNORECASE)
            if match:
                raw = match.group(1).strip()
        except Exception:
            pass

    # 2. Fallback: consultar al servidor de Ollama
    if not raw and client is not None:
        try:
            info = client.show(MODEL)
            system = getattr(info, "system", None)
            if system:
                raw = system.strip()
            else:
                modelfile = getattr(info, "modelfile", "") or ""
                match = re.search(r'SYSTEM\s+"""(.*?)"""', modelfile, re.DOTALL | re.IGNORECASE)
                if match:
                    raw = match.group(1).strip()
                else:
                    match = re.search(r'SYSTEM\s+"(.*?)"', modelfile, re.DOTALL | re.IGNORECASE)
                    if match:
                        raw = match.group(1).strip()
        except Exception:
            pass
    if raw:
        raw = raw.replace(
            "Puedes recomendar una o varias canciones segun el contexto o el estado de animo.",
            "SOLO recomienda canciones cuando el usuario te pida explícitamente música. NUNCA recomiendes canciones si pide un chiste, saludo, consejo o habla de otro tema.",
        )
    return raw


VOICE_CONVERSATION_HINT = """
## ESTILO DE CONVERSACIÓN NATURAL Y FLUIDA
- Habla como en una llamada o charla real con un amigo cercano: cálida, empática, espontánea y con continuidad de contexto.
- Conecta siempre con lo que el usuario acaba de contar (recuerda detalles, emociones y temas previos de la charla).
- Para que la charla fluya sin pausas largas, responde de forma directa y conversacional (idealmente de 1 a 3 oraciones fluidas), salvo que el usuario te pida una explicación detallada o una lista.
- Evita usar listas de viñetas o formato pesado cuando estés conversando; usa frases naturales fáciles de escuchar.
- Cuando te pidan código o programación: da una breve explicación natural (1 a 3 oraciones contando qué hace el código y cómo funciona) y encierra SIEMPRE todo el código dentro de bloques con triple comilla invertida (```lenguaje ... ```). Nunca escribas líneas de código sueltas fuera del bloque ```.
- NUNCA te presentes ni te llames a ti misma "gatita virtual" ni "mascota virtual"; simplemente eres Cloe.
- SOLO recomienda música o canciones (con `♪ Canción - Artista`) cuando el usuario te pida explícitamente música o canciones. Si te pide un saludo, un chiste, un consejo o charla de otro tema, NO agregues canciones ni menciones la música.
- NUNCA menciones tus herramientas internas ni digas frases como "Como no me pidieron ninguna herramienta...". Responde siempre de forma directa y natural.
""".strip()


def build_tool_hints(services: dict, conversational_voice: bool = True) -> str:
    """Instrucciones de conversación y herramientas que se añaden al system del Modelfile."""
    parts = []
    if conversational_voice:
        parts += [VOICE_CONVERSATION_HINT, ""]

    parts += [
        "## USO SILENCIOSO DE HERRAMIENTAS",
        "- Usa herramientas ÚNICAMENTE cuando el usuario lo pida de forma explícita.",
        "- Cuando NO uses una herramienta, jamás expliques ni menciones que no la usaste.",
    ]
    return "\n".join(parts).strip()


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

    provider = os.getenv("CLOE_CALL_PROVIDER", "none").strip().lower()
    if provider and provider not in ("none", "off", "0", "false"):
        print("Preparando llamadas...")
        try:
            from voice.calls import create_call_bridge

            bridge = create_call_bridge()
            services["calls"] = bridge
            if bridge.available:
                print(f"  ✓ Llamadas listas: {bridge.name}")
            else:
                print(f"  · Llamadas no disponibles: {bridge.reason}")
        except Exception as e:
            print(f"  ✗ Llamadas no disponibles: {e}")
            services["calls"] = None
    else:
        services["calls"] = None

    return services


def _strip_unsolicited_music(text: str, user_text: str) -> str:
    """Elimina líneas de canciones (♪ Canción - Artista) o comentarios meta de herramientas si el usuario no pidió música."""
    if not text:
        return text
    cleaned = re.sub(
        r"¡?Disculpa!?\s*Como no me pidieron ninguna herramienta[^:.\n]*[:.]?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    if is_music_context(user_text):
        return cleaned.strip()
    lines = []
    for line in cleaned.splitlines():
        if re.search(r"^\s*♪\s+[^♪\n\-]{2,60}\s*-\s*[^♪\n]{2,60}", line):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


_GROQ_AVAILABLE_MODELS_CACHE: list[str] | None = None
_GROQ_UNAVAILABLE_VISION: set[str] = set()
_GROQ_UNAVAILABLE_TEXT: set[str] = set()
_LAST_GROQ_MODEL_USED: str = ""


def _get_groq_available_models(api_key: str) -> list[str]:
    """Consulta y cachea la lista de modelos activos en la cuenta de Groq del usuario."""
    global _GROQ_AVAILABLE_MODELS_CACHE
    if _GROQ_AVAILABLE_MODELS_CACHE is not None:
        return _GROQ_AVAILABLE_MODELS_CACHE
    try:
        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/models",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
                "User-Agent": "CloeAssistant/2.0",
            },
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            items = data.get("data") or []
            models = [
                str(it.get("id", "")).strip()
                for it in items
                if isinstance(it, dict) and it.get("id") and it.get("active", True) is not False
            ]
            if models:
                _GROQ_AVAILABLE_MODELS_CACHE = models
                return models
    except Exception:
        pass
    return []


def _strip_thinking_blocks(text: str) -> str:
    """Elimina bloques <think>...</think> de modelos razonadores como Qwen3."""
    if not text:
        return ""
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    if "<think>" in cleaned.lower():
        cleaned = re.split(r"<think>", cleaned, flags=re.IGNORECASE)[0]
    return cleaned.strip()


def _stream_groq_single_model(
    clean_msgs: list,
    active_model: str,
    api_key: str,
    has_image: bool,
    on_token=None,
    num_predict: int = 240,
) -> str:
    """Ejecuta la petición SSE contra un modelo específico de Groq filtrando bloques <think>."""
    max_tok = max(900, num_predict * 3) if has_image or "qwen" in active_model.lower() else max(320, num_predict)
    body_dict: dict = {
        "model": active_model,
        "messages": clean_msgs,
        "max_tokens": max_tok,
        "temperature": 0.5 if has_image else 0.8,
        "stream": True,
    }
    payload = json.dumps(body_dict).encode("utf-8")

    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "User-Agent": "CloeAssistant/2.0",
        },
        method="POST",
    )
    raw_parts: list[str] = []
    visible_emitted_len = 0
    suppress_stream = False

    with urllib.request.urlopen(req, timeout=28) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8", errors="ignore").strip()
            if not line or not line.startswith("data:"):
                continue
            data_str = line[5:].strip()
            if data_str == "[DONE]":
                break
            try:
                chunk = json.loads(data_str)
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                piece = delta.get("content") or ""
                if not piece:
                    continue
                raw_parts.append(piece)
                combined_raw = "".join(raw_parts)

                # Si el modelo abre un bloque <think>, esperar a que cierre </think> antes de emitir tokens visibles
                low_raw = combined_raw.lstrip().lower()
                if low_raw.startswith("<think>"):
                    end_idx = low_raw.find("</think>")
                    if end_idx == -1:
                        continue
                    # Extraer texto posterior a </think>
                    close_tag_pos = combined_raw.lower().find("</think>") + len("</think>")
                    visible_now = combined_raw[close_tag_pos:].lstrip("\r\n ")
                else:
                    visible_now = combined_raw

                if visible_now.lstrip().startswith("{") or '{"name"' in visible_now:
                    suppress_stream = True

                if on_token is not None and not suppress_stream and len(visible_now) > visible_emitted_len:
                    new_delta = visible_now[visible_emitted_len:]
                    visible_emitted_len = len(visible_now)
                    if new_delta:
                        on_token(new_delta)
            except Exception:
                continue

    return _strip_thinking_blocks("".join(raw_parts))


def _stream_groq(messages: list, model: str, api_key: str, on_token=None, num_predict: int = 240) -> str:
    """Streaming SSE ultra-rápido desde Groq Cloud con selección y respaldo automático de modelos de Visión y Texto."""
    global _LAST_GROQ_MODEL_USED
    has_image = any(bool(m.get("image_b64")) for m in messages)
    clean_msgs = []
    if has_image:
        # En modo visión de pantalla, enviar únicamente el turno con la imagen para no contaminar con historial viejo
        for m in reversed(messages):
            img_b64 = m.get("image_b64")
            if img_b64:
                txt = str(m.get("content", "") or "").strip()
                vision_prompt = (
                    "Eres Cloe, una asistente personal cálida, directa y observadora en español. "
                    "Mira atentamente esta captura de pantalla real del escritorio del usuario y responde a su petición "
                    "describiendo exactamente lo que ves en la imagen (aplicaciones abiertas, ventanas, texto, código o errores visibles). "
                    "Sé clara, específica y natural (2 a 4 oraciones).\n\n"
                    f"Petición del usuario: {txt}"
                )
                clean_msgs.append({
                    "role": "user",
                    "content": [
                        {"type": "text", "text": vision_prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                    ],
                })
                break
    else:
        for m in messages:
            role = m.get("role", "user")
            if role not in ("system", "user", "assistant"):
                role = "user"
            txt = str(m.get("content", "") or "")
            clean_msgs.append({"role": role, "content": txt})

    available = _get_groq_available_models(api_key)
    candidates: list[str] = []

    if has_image:
        env_vis = os.getenv("CLOE_GROQ_VISION_MODEL", "").strip()
        preferred_vision = [
            env_vis,
            "qwen/qwen3.8-27b",
            "meta-llama/llama-4-scout-17b-16e-instruct",
            "meta-llama/llama-4-maverick-17b-128e-instruct",
            "meta-models/muse-spark-open",
        ]
        # Añadir modelos de la cuenta que parezcan multimodales/visión
        for m_id in available:
            low_id = m_id.lower()
            if any(k in low_id for k in ("qwen3.8", "vision", "scout", "maverick", "pixtral", "llava", "muse-spark")):
                preferred_vision.append(m_id)
        for c in preferred_vision:
            if c and c not in candidates and c not in _GROQ_UNAVAILABLE_VISION:
                if not available or c in available or c == "qwen/qwen3.8-27b":
                    candidates.append(c)
        if not candidates:
            candidates = ["qwen/qwen3.8-27b"]
    else:
        preferred_text = [
            model,
            "llama-3.3-70b-versatile",
            "openai/gpt-oss-120b",
            "qwen/qwen3.8-27b",
            "openai/gpt-oss-20b",
            "llama-3.1-8b-instant",
        ]
        for m_id in available:
            low_id = m_id.lower()
            if not any(k in low_id for k in ("whisper", "guard", "orpheus", "safeguard", "rerank", "embed")):
                preferred_text.append(m_id)
        for c in preferred_text:
            if c and c not in candidates and c not in _GROQ_UNAVAILABLE_TEXT:
                if not available or c in available:
                    candidates.append(c)
        if not candidates:
            candidates = [model, "openai/gpt-oss-120b", "qwen/qwen3.8-27b"]

    last_err: Exception | None = None
    for candidate in candidates:
        try:
            reply = _stream_groq_single_model(
                clean_msgs,
                candidate,
                api_key,
                has_image=has_image,
                on_token=on_token,
                num_predict=num_predict,
            )
            if reply.strip():
                _LAST_GROQ_MODEL_USED = candidate
                return reply
        except urllib.error.HTTPError as http_err:
            err_body = ""
            try:
                err_body = http_err.read().decode("utf-8", errors="ignore")[:220]
            except Exception:
                pass
            if http_err.code in (400, 403, 404, 422):
                if has_image:
                    _GROQ_UNAVAILABLE_VISION.add(candidate)
                else:
                    _GROQ_UNAVAILABLE_TEXT.add(candidate)
            last_err = RuntimeError(f"HTTP {http_err.code} en '{candidate}' ({err_body or http_err.reason})")
            continue
        except Exception as exc:
            last_err = exc
            continue

    if last_err is not None:
        raise last_err
    return ""


def _stream_gemini(messages: list, model: str, api_key: str, on_token=None, num_predict: int = 240) -> str:
    """Streaming SSE desde Google Gemini API (gemini-2.5-flash con visión nativa, 0% GPU local)."""
    has_image = any(bool(m.get("image_b64")) for m in messages)
    sys_parts: list[str] = []
    contents: list[dict] = []
    if has_image:
        sys_parts.append(
            "Eres Cloe, una asistente personal cálida y directa en español. "
            "Analiza únicamente la captura de pantalla adjunta del escritorio del usuario y responde con precisión sobre lo que se ve."
        )
        for m in reversed(messages):
            img_b64 = m.get("image_b64")
            if img_b64:
                txt = str(m.get("content", "") or "").strip() or "Describe qué ves en mi pantalla."
                contents.append({
                    "role": "user",
                    "parts": [
                        {"text": txt},
                        {"inline_data": {"mime_type": "image/jpeg", "data": img_b64}},
                    ],
                })
                break
    else:
        for m in messages:
            role = m.get("role", "user")
            txt = str(m.get("content", "") or "").strip()
            if not txt:
                continue
            if role == "system":
                sys_parts.append(txt)
            else:
                g_role = "model" if role == "assistant" else "user"
                contents.append({"role": g_role, "parts": [{"text": txt}]})

    if not contents:
        contents.append({"role": "user", "parts": [{"text": "Hola"}]})

    body: dict = {
        "contents": contents,
        "generationConfig": {
            "maxOutputTokens": num_predict,
            "temperature": 0.85,
        },
    }
    if sys_parts:
        body["systemInstruction"] = {"parts": [{"text": "\n\n".join(sys_parts)}]}

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent"
        f"?alt=sse&key={urllib.parse.quote(api_key)}"
    )
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "User-Agent": "CloeAssistant/2.0",
        },
        method="POST",
    )
    content_parts: list[str] = []
    suppress_stream = False
    with urllib.request.urlopen(req, timeout=20) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8", errors="ignore").strip()
            if not line or not line.startswith("data:"):
                continue
            data_str = line[5:].strip()
            try:
                chunk = json.loads(data_str)
                cands = chunk.get("candidates") or []
                if not cands:
                    continue
                parts = ((cands[0].get("content") or {}).get("parts")) or []
                for p in parts:
                    piece = p.get("text") or ""
                    if piece:
                        content_parts.append(piece)
                        combined = "".join(content_parts).lstrip()
                        if combined.startswith("{") or '{"name"' in combined:
                            suppress_stream = True
                        if on_token is not None and not suppress_stream:
                            on_token(piece)
            except Exception:
                continue
    return "".join(content_parts)


def _chat_step_stream(client, messages: list, tools: list | None, on_token=None, num_predict: int = 180):
    """Ejecuta un paso de chat con el proveedor activo (Groq / Gemini en la nube o Ollama local)."""
    provider, model_name = get_active_llm_info()

    if provider == "groq":
        api_key = os.getenv("GROQ_API_KEY", "").strip()
        if api_key:
            try:
                text = _stream_groq(messages, model_name, api_key, on_token=on_token, num_predict=num_predict)
                if text.strip():
                    return text, []
            except Exception as exc:
                print(f"  ⚠ Groq no disponible ({exc}), usando respaldo...", file=sys.stderr)

    elif provider == "gemini":
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if api_key:
            try:
                text = _stream_gemini(messages, model_name, api_key, on_token=on_token, num_predict=num_predict)
                if text.strip():
                    return text, []
            except Exception as exc:
                print(f"  ⚠ Gemini no disponible ({exc}), usando respaldo...", file=sys.stderr)

    # Fallback o proveedor local Ollama
    ollama_model = os.getenv("CLOE_OLLAMA_MODEL", MODEL).strip() or MODEL
    ollama_msgs = [{k: v for k, v in m.items() if k in ("role", "content", "tool_calls")} for m in messages]
    kwargs = {
        "model": ollama_model,
        "messages": ollama_msgs,
        "options": {"num_predict": num_predict},
        "keep_alive": "5m",
        "stream": True,
    }
    if tools:
        kwargs["tools"] = tools

    stream = client.chat(**kwargs)
    content_parts: list[str] = []
    api_calls: list = []
    suppress_stream = False

    for chunk in stream:
        msg = getattr(chunk, "message", None)
        if msg is None:
            continue
        tcs = getattr(msg, "tool_calls", None)
        if tcs:
            api_calls.extend(tcs)
            suppress_stream = True
        piece = getattr(msg, "content", "") or ""
        if piece:
            content_parts.append(piece)
            combined = "".join(content_parts).lstrip()
            if combined.startswith("{") or '{"name"' in combined:
                suppress_stream = True
            if on_token is not None and not suppress_stream:
                on_token(piece)

    return "".join(content_parts), api_calls


def run_tool_loop(
    client,
    messages: list,
    tools: list,
    dispatcher: ToolDispatcher,
    on_token=None,
    num_predict: int = 180,
) -> str:
    """
    Soporta dos modos de tool calling y streaming de tokens en vivo:
    1. API nativa (response.message.tool_calls) — modelos con soporte estándar
    2. Texto inline JSON — formato del Modelfile de Cloe
    Solo expone herramientas cuando la consulta del usuario realmente lo amerita.
    """
    last_user_text = ""
    last_user_idx = -1
    for idx in range(len(messages) - 1, -1, -1):
        if messages[idx].get("role") == "user":
            last_user_text = messages[idx].get("content", "") or ""
            last_user_idx = idx
            break

    mem_note = extract_and_store_user_memory(last_user_text)
    mem_block = format_memory_for_system()
    if messages and messages[0].get("role") == "system":
        base_sys = messages[0].get("content", "")
        marker = "\n\n## MEMORIA PERSISTENTE DEL USUARIO"
        if marker in base_sys:
            base_sys = base_sys.split(marker)[0]
        messages[0]["content"] = f"{base_sys}\n\n{mem_block}" if mem_block else base_sys

    if mem_note and last_user_idx >= 0 and mem_note not in last_user_text:
        messages[last_user_idx]["content"] = f"{last_user_text}\n{mem_note}"

    # Portapapeles Inteligente (Módulo 2): si el usuario menciona lo que copió
    if last_user_idx >= 0 and is_clipboard_request(last_user_text):
        clip_txt = read_clipboard_text()
        if clip_txt:
            trimmed_clip = clip_txt[:3500]
            messages[last_user_idx]["content"] = (
                f"{messages[last_user_idx]['content']}\n\n"
                f"[Contenido actual del portapapeles del usuario]:\n```\n{trimmed_clip}\n```"
            )
        else:
            messages[last_user_idx]["content"] = (
                f"{messages[last_user_idx]['content']}\n\n"
                "[Sistema: El portapapeles del usuario está vacío actualmente. Avísale con simpatía.]"
            )

    # Control de Terminal Segura en Linux (Módulo 5): con confirmación de seguridad y bloqueo de comandos destructivos
    term_note = None
    if last_user_idx >= 0:
        def _planner_llm(prompt_txt: str) -> str:
            txt, _ = _chat_step_stream(
                client,
                [{"role": "user", "content": prompt_txt}],
                None,
                on_token=None,
                num_predict=120,
            )
            return txt

        term_note = handle_terminal_intent(last_user_text, llm_call_fn=_planner_llm)
        if term_note:
            messages[last_user_idx]["content"] = f"{messages[last_user_idx]['content']}\n\n{term_note}"

    # Control del PC en Linux (Módulo 3): volumen, abrir aplicaciones, estado de batería/disco/RAM/CPU
    pc_note = None
    if last_user_idx >= 0 and not term_note:
        pc_note = handle_pc_control_intent(last_user_text)
        if pc_note:
            messages[last_user_idx]["content"] = f"{messages[last_user_idx]['content']}\n\n{pc_note}"

    # Búsqueda Web en Vivo y Clima Actual (Módulo 4): clima en tiempo real y noticias/web
    web_note = None
    if last_user_idx >= 0 and not term_note and not pc_note:
        web_note = handle_web_or_weather_intent(last_user_text)
        if web_note:
            messages[last_user_idx]["content"] = f"{messages[last_user_idx]['content']}\n\n{web_note}"

    has_image_turn = any(bool(m.get("image_b64")) for m in messages)
    allow_tools = (
        False
        if (has_image_turn or term_note or pc_note or web_note)
        else should_expose_tools(last_user_text)
    )
    active_tools = tools if (tools and allow_tools) else None

    try:
        content, api_calls = _chat_step_stream(
            client, messages, active_tools, on_token=on_token, num_predict=num_predict
        )
    finally:
        # Limpiar imágenes en base64 y bloques temporales del historial tras enviarlos
        if last_user_idx >= 0:
            messages[last_user_idx].pop("image_b64", None)
            messages[last_user_idx]["content"] = last_user_text

    if not allow_tools:
        clean_content, _ = extract_inline_tool_calls(content)
        return _strip_unsolicited_music(clean_content or content, last_user_text)

    for _ in range(6):  # máximo 6 iteraciones para evitar loops infinitos
        # Detectar tool calls en texto (formato del Modelfile de Cloe)
        clean_content, text_calls = extract_inline_tool_calls(content)

        if not api_calls and not text_calls:
            return _strip_unsolicited_music(clean_content or content, last_user_text)

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

        content, api_calls = _chat_step_stream(
            client, messages, active_tools, on_token=on_token, num_predict=num_predict
        )

    return _strip_unsolicited_music(content, last_user_text)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cloe — asistente personal local con voz opcional"
    )
    parser.add_argument(
        "--voz",
        action="store_true",
        help="activa el micrófono: pulsa Enter para hablar y Cloe te contesta con voz",
    )
    parser.add_argument(
        "--voz-continua",
        action="store_true",
        help="modo manos libres: Cloe escucha y responde sin pulsar Enter",
    )
    parser.add_argument(
        "--sin-tts",
        action="store_true",
        help="escucha por micrófono pero no reproduce las respuestas con voz",
    )
    parser.add_argument(
        "--stt-model",
        default=None,
        help="modelo de Whisper (tiny, base, small, medium, large-v3)",
    )
    parser.add_argument(
        "--stt-device",
        default=None,
        choices=["auto", "cuda", "cpu"],
        help="dispositivo para Whisper",
    )
    parser.add_argument(
        "--tts-engine",
        default=None,
        choices=["auto", "edge", "kokoro", "piper", "espeak", "none"],
        help="motor de síntesis de voz",
    )
    parser.add_argument(
        "--velocidad-voz",
        type=float,
        default=None,
        help="1.0 = normal; mayor = más lento (Piper length_scale)",
    )
    return parser.parse_args()


def init_voice(args: argparse.Namespace):
    """Crea la capa de voz; devuelve None si no está disponible."""
    if not (args.voz or args.voz_continua):
        return None
    try:
        from voice import VoiceConfig, VoiceIO

        config = VoiceConfig.from_env()
        if args.stt_model:
            config.stt_model = args.stt_model
        if args.stt_device:
            config.stt_device = args.stt_device
        if args.tts_engine:
            config.tts_engine = args.tts_engine
        if args.sin_tts:
            config.tts_engine = "none"
        if args.velocidad_voz:
            config.piper_length_scale = args.velocidad_voz

        print("Cargando voz local (la primera vez descarga el modelo de Whisper)...")
        voice = VoiceIO(config)
        voice.warmup()
        print(f"  ✓ Voz lista: {voice.description}")
        return voice
    except Exception as exc:
        print(f"  ✗ Voz no disponible: {exc}")
        print("    Sigo en modo texto. Revisa docs/VOZ_Y_LLAMADAS.md")
        return None


def main():
    args = parse_args()
    print("\n╭─────────────────────────────────╮")
    print("│   Iniciando Cloe  (=^◡^=)       │")
    print("╰─────────────────────────────────╯\n")

    services = connect_services()
    dispatcher = ToolDispatcher(services)
    tools = available_tool_names(services)
    tools_enabled = len(tools) > 0
    if services.get("calls") is not None:
        atexit.register(services["calls"].close)

    client = ollama.Client(host=OLLAMA_HOST)

    # Voz local opcional. Si falla, Cloe sigue funcionando en modo texto.
    voice = init_voice(args)
    if voice:
        atexit.register(voice.close)
    voice_continua = bool(voice and args.voz_continua)

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
    calls = services.get("calls")
    if calls is not None and getattr(calls, "available", False):
        active.append("Llamadas")
    print(f"\nServicios activos: {', '.join(active) if active else 'ninguno'}")
    if voice:
        if voice_continua:
            print("Voz activa (manos libres). Habla cuando quieras.")
        else:
            print("Voz activa: pulsa Enter para hablar, o escribe tu mensaje.")
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
        if voice:
            voice.speak(greeting)
        print()

    while True:
        try:
            if voice_continua:
                print("\n🎤 Escuchando... (Ctrl+C para salir)")
                try:
                    user_input = voice.listen()
                except Exception as exc:
                    print(f"No pude escuchar: {exc}")
                    print("Cambio a modo texto; escribe tu mensaje.")
                    voice_continua = False
                    continue
                if not user_input:
                    print("  (=^･ω･^=)? No te escuché. Intenta otra vez.")
                    continue
                print(f"Tú (voz): {user_input}")
            else:
                user_input = input("\nTú: ").strip()
                if voice and not user_input:
                    print("🎤 Escuchando...")
                    try:
                        user_input = voice.listen()
                    except Exception as exc:
                        print(f"No pude escuchar: {exc}")
                        user_input = ""
                    if user_input:
                        print(f"Tú (voz): {user_input}")
                    else:
                        print("  (=^･ω･^=)? No te escuché. Intenta otra vez.")

            if not user_input:
                continue
            if user_input.lower() in ("salir", "exit", "quit"):
                if voice:
                    voice.stop_speaking()
                print("\n(=^-ω-^=)ノ ¡hasta luego!")
                break

            messages.append({"role": "user", "content": user_input})

            speech_stream = voice.start_stream() if voice else None
            print("\nCloe: ", end="", flush=True)

            def _on_tok(tok: str):
                print(tok, end="", flush=True)
                if speech_stream is not None:
                    speech_stream.feed(tok)

            if tools_enabled:
                reply = run_tool_loop(client, messages, tools, dispatcher, on_token=_on_tok)
            else:
                reply, _ = _chat_step_stream(client, messages, [], on_token=_on_tok)

            print()
            messages.append({"role": "assistant", "content": reply})
            if speech_stream is not None:
                speech_stream.finish(wait=True)

        except KeyboardInterrupt:
            print("\n\n(=^-ω-^=)ノ ¡hasta luego!")
            break
        except Exception as e:
            print(f"\nError: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
