import json
from typing import Any

import services.spotify_tools as sp_mod
import services.calendar_tools as cal_mod
import services.gmail_tools as gm_mod

# ── Definiciones para ollama tool calling ─────────────────────────────────────

TOOL_DEFINITIONS = [
    # Spotify — estado
    {
        "type": "function",
        "function": {
            "name": "spotify_now_playing",
            "description": "Obtiene la canción que está sonando ahora en Spotify",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "spotify_recommendations",
            "description": "Obtiene recomendaciones de canciones personalizadas según el historial del usuario",
            "parameters": {
                "type": "object",
                "properties": {
                    "mood": {
                        "type": "string",
                        "description": "Estado de ánimo o género deseado (ej: alegre, triste, chill, energía)",
                    }
                },
                "required": [],
            },
        },
    },
    # Spotify — control
    {
        "type": "function",
        "function": {
            "name": "spotify_play",
            "description": "Reproduce una canción, álbum o artista en Spotify",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Nombre de canción, álbum o artista"}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "spotify_queue",
            "description": "Añade una canción a la cola de reproducción de Spotify",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Nombre de canción o artista"}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "spotify_pause",
            "description": "Pausa la música en Spotify",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "spotify_resume",
            "description": "Reanuda la música pausada en Spotify",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "spotify_next",
            "description": "Salta a la siguiente canción en Spotify",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "spotify_previous",
            "description": "Vuelve a la canción anterior en Spotify",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "spotify_volume",
            "description": "Ajusta el volumen de Spotify entre 0 y 100",
            "parameters": {
                "type": "object",
                "properties": {
                    "level": {"type": "integer", "description": "Nivel de volumen (0-100)"}
                },
                "required": ["level"],
            },
        },
    },
    # Calendario
    {
        "type": "function",
        "function": {
            "name": "calendar_today",
            "description": "Obtiene los eventos de hoy en el calendario de Google",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calendar_upcoming",
            "description": "Obtiene los próximos eventos del calendario de Google",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Cuántos días hacia adelante buscar (default: 7)"}
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calendar_create",
            "description": "Crea un nuevo evento en el calendario de Google",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Título del evento"},
                    "date": {"type": "string", "description": "Fecha y hora del evento (ej: '2025-06-10 15:00' o 'mañana a las 3pm')"},
                    "duration_minutes": {"type": "integer", "description": "Duración en minutos (default: 60)"},
                    "description": {"type": "string", "description": "Descripción opcional"},
                },
                "required": ["title", "date"],
            },
        },
    },
    # Gmail
    {
        "type": "function",
        "function": {
            "name": "gmail_unread",
            "description": "Obtiene los correos no leídos del inbox de Gmail",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Número máximo de correos (default: 5)"}
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gmail_send",
            "description": "Envía un correo electrónico desde Gmail",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Dirección de correo del destinatario"},
                    "subject": {"type": "string", "description": "Asunto del correo"},
                    "body": {"type": "string", "description": "Cuerpo del mensaje"},
                },
                "required": ["to", "subject", "body"],
            },
        },
    },
]


# ── Dispatcher ────────────────────────────────────────────────────────────────

class ToolDispatcher:
    def __init__(self, services: dict):
        self._sp = services.get("spotify")
        self._cal = services.get("calendar")
        self._gmail = services.get("gmail")

    def run(self, name: str, args: dict) -> str:
        handlers = {
            "spotify_now_playing":   self._spotify_now_playing,
            "spotify_recommendations": self._spotify_recommendations,
            "spotify_play":          self._spotify_play,
            "spotify_queue":         self._spotify_queue,
            "spotify_pause":         self._spotify_pause,
            "spotify_resume":        self._spotify_resume,
            "spotify_next":          self._spotify_next,
            "spotify_previous":      self._spotify_previous,
            "spotify_volume":        self._spotify_volume,
            "calendar_today":        self._calendar_today,
            "calendar_upcoming":     self._calendar_upcoming,
            "calendar_create":       self._calendar_create,
            "gmail_unread":          self._gmail_unread,
            "gmail_send":            self._gmail_send,
        }
        handler = handlers.get(name)
        if not handler:
            return json.dumps({"error": f"Herramienta desconocida: {name}"})
        try:
            result = handler(**args)
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)})

    # Spotify helpers
    def _require_spotify(self) -> dict | None:
        if not self._sp:
            return {"success": False, "error": "Spotify no está configurado."}
        return None

    def _spotify_now_playing(self):
        err = self._require_spotify()
        return err or sp_mod.get_current_track(self._sp)

    def _spotify_recommendations(self, mood: str = ""):
        err = self._require_spotify()
        if err:
            return err
        result = sp_mod.get_recommendations(self._sp, mood)
        if result.get("method") == "api":
            lines = [f"♪ {r['name']} - {r['artist']}" for r in result["tracks"]]
            return {"success": True, "recommendations": "\n".join(lines)}
        # browser_search fallback
        return result

    def _spotify_play(self, query: str):
        err = self._require_spotify()
        return err or sp_mod.play_track(self._sp, query)

    def _spotify_queue(self, query: str):
        err = self._require_spotify()
        return err or sp_mod.add_to_queue(self._sp, query)

    def _spotify_pause(self):
        err = self._require_spotify()
        return err or sp_mod.pause_playback(self._sp)

    def _spotify_resume(self):
        err = self._require_spotify()
        return err or sp_mod.resume_playback(self._sp)

    def _spotify_next(self):
        err = self._require_spotify()
        return err or sp_mod.next_track(self._sp)

    def _spotify_previous(self):
        err = self._require_spotify()
        return err or sp_mod.previous_track(self._sp)

    def _spotify_volume(self, level: int):
        err = self._require_spotify()
        return err or sp_mod.set_volume(self._sp, level)

    # Calendar helpers
    def _require_calendar(self) -> dict | None:
        if not self._cal:
            return {"success": False, "error": "Google Calendar no está configurado."}
        return None

    def _calendar_today(self):
        err = self._require_calendar()
        return err or cal_mod.get_today_events(self._cal)

    def _calendar_upcoming(self, days: int = 7):
        err = self._require_calendar()
        return err or cal_mod.get_upcoming_events(self._cal, days)

    def _calendar_create(self, title: str, date: str, duration_minutes: int = 60, description: str = ""):
        err = self._require_calendar()
        return err or cal_mod.create_event(self._cal, title, date, duration_minutes, description)

    # Gmail helpers
    def _require_gmail(self) -> dict | None:
        if not self._gmail:
            return {"success": False, "error": "Gmail no está configurado."}
        return None

    def _gmail_unread(self, limit: int = 5):
        err = self._require_gmail()
        return err or gm_mod.get_unread_emails(self._gmail, limit)

    def _gmail_send(self, to: str, subject: str, body: str):
        err = self._require_gmail()
        return err or gm_mod.send_email(self._gmail, to, subject, body)


def available_tool_names(services: dict) -> list[dict]:
    """Filtra herramientas según los servicios disponibles."""
    spotify_tools = {
        "spotify_now_playing", "spotify_recommendations", "spotify_play",
        "spotify_queue", "spotify_pause", "spotify_resume",
        "spotify_next", "spotify_previous", "spotify_volume",
    }
    calendar_tools = {"calendar_today", "calendar_upcoming", "calendar_create"}
    gmail_tools = {"gmail_unread", "gmail_send"}

    active: set[str] = set()
    if services.get("spotify"):
        active |= spotify_tools
    if services.get("calendar"):
        active |= calendar_tools
    if services.get("gmail"):
        active |= gmail_tools

    return [t for t in TOOL_DEFINITIONS if t["function"]["name"] in active]
