import sys
import os
import re
import glob
import json
import math
import time
import subprocess
import urllib.parse
import urllib.request
import logging
import random
import threading
import atexit
from dotenv import load_dotenv

# Añadir raíz del proyecto al path para imports
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

load_dotenv(os.path.join(_ROOT, ".env"), override=True)
logging.getLogger("spotipy").setLevel(logging.CRITICAL)
logging.getLogger("urllib3").setLevel(logging.CRITICAL)

# En Linux con Wayland, el protocolo xdg-shell bloquea WindowStaysOnTopHint.
# Si XWayland/X11 (DISPLAY) está disponible, usar 'xcb' garantiza que Cloe esté SIEMPRE encima de todas las ventanas.
if sys.platform.startswith("linux") and os.environ.get("DISPLAY") and not os.environ.get("QT_QPA_PLATFORM"):
    os.environ["QT_QPA_PLATFORM"] = "xcb"

from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit,
    QPushButton, QVBoxLayout, QHBoxLayout, QFrame, QMenu,
    QTextEdit, QComboBox, QSlider, QScrollArea,
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QPoint, QRectF, QUrl,
)
from PyQt6.QtGui import (
    QPainter, QPainterPath, QColor, QLinearGradient, QRadialGradient,
    QFont, QAction, QPen, QPixmap, QImage, QDesktopServices, QRegion,
)

import ollama
from chat import (
    connect_services, get_modelfile_system, build_tool_hints,
    detect_songs, is_music_context, run_tool_loop, OLLAMA_HOST,
    get_active_llm_info, save_env_var, unload_ollama_vram,
)
from tools import ToolDispatcher, available_tool_names
from services.spotify_tools import play_track
from services.memory_tools import parse_reminder_request
from services.vision_clipboard_tools import (
    is_screen_vision_request,
    capture_screen_jpeg,
    get_active_window_context,
)
from services.terminal_tools import pop_last_terminal_card


# ── Repertorio de Kaomojis y Prompts Espontáneos ──────────────────────────────
SOLO_PROMPTS = [
    "Manda UN kaomoji con un comentario muy corto y gracioso para animar al usuario. Máximo 1 oración.",
    "Di algo random, cálido e inesperado, como si de repente se te ocurrió algo. Muy corto, máximo 1 oración.",
    "Pregunta de forma casual y cercana cómo va el día. 1 oración.",
    "Dí algo gracioso o un consejo cortísimo con buena vibra. 1 oración máximo.",
    "Comenta algo sobre lo que estás 'haciendo' en este momento como si fueras real. Muy corto.",
]

NEKO_KAOMOJIS = {
    "idle": ["(=^･ω･^=)", "ฅ^•ﻌ•^ฅ", "(=^◡^=)", "(=^･ｪ･^=)", "( =①ω①=)", "(=^-ω-^=)"],
    "listening": ["(=^･ω･^=)?", "(=^･ᆺ･^=)？", "ฅ(=^･ᆺ･^=)ฅ", "(= ^._.^=)"],
    "thinking": ["(=｀ω´=)?", "／(=✪ x ✪=)＼", "(ﾐዋ ﻌ ዋﾐ)?", "(=^‥^=)..."],
    "speaking": ["(=^▽^=)ノ", "(=^･∇･^=)ﾉ", "ฅ(^•ω•^ฅ)", "(=^･ω･^=)♪", "(=^◡^=)♡"],
    "happy": ["ฅ^•ﻌ•^ฅ ♥", "(=´∇｀=)", "(ﾉ^ヮ^)ﾉ*:・ﾟ✧", "(=^･◡･^=)"],
    "laser": ["／(=✪ x ✪=)＼", "(=｀ω´=)⚡", "ฅ(ﾐ✪ ﻌ ✪ﾐ)ฅ"],
    "sleeping": ["( -ω-) zZz", "(=‐ω‐=)..zzZ", "( ˘ω˘ )🐾"],
}

# ── Sprites Pixel-Art 16x16 (de mascota_virtual_ia_local_pop_up.html) ─────────
NEKO_IDLE_1 = [
    "..OO........OO..",
    ".OPPO......OPPO.",
    ".OHHOOOOOOOOHHO.",
    ".OHHHHHHHHHHHHO.",
    "..OBBBBBBBBBBO..",
    ".KOBWWBBBBWWBOK.",
    "..OBWEBBBBWEBO..",
    ".KOBBBBPBBBBOK..",
    "...OBBBBBBBBO.OO",
    "...OCCCCCCCCO.OB",
    "..OBBBBGGWWWWOO.",
    "..OBBBWWWWBBO...",
    "..OBBWWWWBBBO...",
    "..OOWWOOOOOWWO..",
    "................",
    "................",
]

NEKO_IDLE_2 = [
    "..OO........OO..",
    ".OPPO......OPPO.",
    ".OHHOOOOOOOOHHO.",
    ".OHHHHHHHHHHHHO.",
    "..OBBBBBBBBBBO..",
    ".KOBWWBBBBWWBOK.",
    "..OBWEBBBBWEBO..",
    ".KOBBBBPBBBBOK..",
    "...OBBBBBBBBO...",
    "...OCCCCCCCCO...",
    "..OBBBBGGWWWWOO.",
    "..OBBBWWWWBBO.OB",
    "..OBBWWWWBBBOOO.",
    "..OOWWOOOOOWWO..",
    "................",
    "................",
]

NEKO_BLINK = [
    "..OO........OO..",
    ".OPPO......OPPO.",
    ".OHHOOOOOOOOHHO.",
    ".OHHHHHHHHHHHHO.",
    "..OBBBBBBBBBBO..",
    ".KOBBBBBBBBBBOK.",
    "..OBEEEBBBEEBO..",
    ".KOBBBBPBBBBOK..",
    "...OBBBBBBBBO.OO",
    "...OCCCCCCCCO.OB",
    "..OBBBBGGWWWWOO.",
    "..OBBBWWWWBBO...",
    "..OBBWWWWBBBO...",
    "..OOWWOOOOOWWO..",
    "................",
    "................",
]

NEKO_TALK = [
    ".OO..........OO.",
    "OPPO........OPPO",
    ".OHHOOOOOOOOHHO.",
    ".OHHHHHHHHHHHHO.",
    "..OBBBBBBBBBBO..",
    ".KOBWWBBBBWWBOK.",
    "..OBWEBBBBWEBO..",
    ".KOBPBMMMMBPBOK.",
    "...OBBMMMMBBO.OO",
    "...OCCCCCCCCO.OB",
    "..OBBBBGGWWWWOO.",
    "..OBBBWWWWBBO...",
    "..OBBWWWWBBBO...",
    "..OOWWOOOOOWWO..",
    "................",
    "................",
]

NEKO_HAPPY = [
    "..OO........OO..",
    ".OPPO......OPPO.",
    ".OHHOOOOOOOOHHO.",
    ".OHHHHHHHHHHHHO.",
    "..OBBBBBBBBBBO..",
    ".KOBEBBBBBEBOK..",
    "..OBEWWEBBWWEBO.",
    ".KOPPBMMMMBPPBOK",
    "...OBBBBBBBBO.OO",
    "...OCCCCCCCCO.OB",
    "..OBBBBGGWWWWOO.",
    "..OBBBWWWWBBO...",
    "..OBBWWWWBBBO...",
    "..OOWWOOOOOWWO..",
    "................",
    "................",
]

NEKO_SLEEP = [
    "................",
    "................",
    "................",
    "....OO....OO....",
    "...OPPO..OPPO...",
    "..OHHHHHHHHHHO..",
    ".OHBBBBBBBBBBHO.",
    ".OBEEEBBBBEEEBO.",
    ".OBBBBBPBBBBBBBO",
    ".OBBBBBBBBBWWWBO",
    ".OCCCCCCCCWWWWBO",
    "..OBBBBBWWWWBBO.",
    "...OOOOOOOOOOO..",
    "................",
    "................",
    "................",
]


def get_palette_for_state(state: str) -> dict[str, str]:
    if state == "thinking":
        return {
            "O": "#131124", "B": "#3b2d5e", "H": "#654ea3", "P": "#ff79c6",
            "W": "#ffffff", "E": "#e0af68", "K": "#c4b5fd", "C": "#7dcfff",
            "G": "#f7768e", "M": "#ff79c6",
        }
    if state == "listening":
        return {
            "O": "#0d1f1d", "B": "#1f4742", "H": "#36756d", "P": "#9ece6a",
            "W": "#ffffff", "E": "#7dcfff", "K": "#a7f3d0", "C": "#9ece6a",
            "G": "#e0af68", "M": "#ff79c6",
        }
    if state == "happy":
        return {
            "O": "#111827", "B": "#2b3954", "H": "#4f6899", "P": "#ff79c6",
            "W": "#ffffff", "E": "#7dcfff", "K": "#cbd5e1", "C": "#ff79c6",
            "G": "#e0af68", "M": "#ff79c6",
        }
    if state == "laser":
        return {
            "O": "#1a0f1a", "B": "#31233b", "H": "#5b3e6e", "P": "#f7768e",
            "W": "#ffffff", "E": "#f7768e", "K": "#f8fafc", "C": "#e0af68",
            "G": "#7dcfff", "M": "#f7768e",
        }
    if state == "sleeping":
        return {
            "O": "#0f1322", "B": "#1e263d", "H": "#334166", "P": "#b86b99",
            "W": "#cbd5e1", "E": "#6b759e", "K": "#64748b", "C": "#4d5885",
            "G": "#9ca3af", "M": "#b86b99",
        }
    return {
        "O": "#0c101c", "B": "#242d47", "H": "#41517d", "P": "#ff79c6",
        "W": "#f8fafc", "E": "#7dcfff", "K": "#94a3b8", "C": "#f7768e",
        "G": "#e0af68", "M": "#ff79c6",
    }


VOICE_PRESETS = {
    "edge": [
        ("Dalia · México (Natural)", "es-MX-DaliaNeural"),
        ("Salomé · Colombia (Cálida)", "es-CO-SalomeNeural"),
        ("Elena · Argentina (Suave)", "es-AR-ElenaNeural"),
        ("Elvira · España (Clara)", "es-ES-ElviraNeural"),
        ("Jorge · México (Masculina)", "es-MX-JorgeNeural"),
    ],
    "kokoro": [
        ("Dora · Femenina (Local)", "ef_dora"),
        ("Alex · Masculina (Local)", "em_alex"),
    ],
    "piper": [
        ("Claude · México High (Local)", "es_MX-claude-high"),
        ("Ald · México Medium (Local)", "es_MX-ald-medium"),
        ("Daniela · Argentina (Local)", "es_AR-daniela-high"),
    ],
}


# ── Estilos Cristal Cloe (Glassmorphism + Paleta Tokyo Night) ───────────
GLASS_PANEL_STYLE = """
QWidget {
    color: #d5dcf9;
    font-family: 'Inter', 'Segoe UI', 'Ubuntu', sans-serif;
}
QTextEdit {
    background-color: rgba(12, 14, 24, 95);
    border: 1px solid rgba(125, 207, 255, 38);
    border-radius: 14px;
    padding: 8px 10px;
    font-size: 12.5px;
    color: #e6ecff;
    selection-background-color: rgba(125, 207, 255, 90);
}
QScrollArea {
    background: transparent;
    border: none;
}
QScrollBar:vertical {
    background: transparent;
    width: 5px;
    margin: 4px 1px;
}
QScrollBar::handle:vertical {
    background: rgba(125, 207, 255, 65);
    border-radius: 2px;
    min-height: 20px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
    height: 0px;
}
QLineEdit {
    background-color: rgba(9, 10, 18, 155);
    border: 1px solid rgba(77, 88, 133, 120);
    border-radius: 12px;
    padding: 6px 11px;
    font-size: 12.5px;
    color: #f0f4ff;
}
QLineEdit:focus {
    background-color: rgba(14, 16, 28, 190);
    border: 1px solid rgba(125, 207, 255, 210);
}
QPushButton {
    background-color: rgba(26, 30, 46, 150);
    border: 1px solid rgba(77, 88, 133, 110);
    border-radius: 9px;
    padding: 4px 9px;
    color: #d5dcf9;
    font-size: 11px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: rgba(42, 48, 74, 195);
    border: 1px solid rgba(125, 207, 255, 190);
    color: #ffffff;
}
QPushButton:pressed {
    background-color: rgba(125, 207, 255, 65);
}
QComboBox {
    background-color: rgba(14, 16, 28, 175);
    border: 1px solid rgba(77, 88, 133, 120);
    border-radius: 8px;
    padding: 3px 8px;
    color: #d5dcf9;
    font-size: 11.5px;
}
QComboBox QAbstractItemView {
    background-color: rgba(18, 21, 33, 245);
    border: 1px solid rgba(125, 207, 255, 120);
    color: #d5dcf9;
    selection-background-color: rgba(125, 207, 255, 75);
}
QSlider::groove:horizontal {
    height: 4px;
    background: rgba(77, 88, 133, 110);
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: #7dcfff;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #ffffff;
    width: 12px;
    height: 12px;
    margin: -4px 0;
    border-radius: 6px;
}
"""


def paint_frosted_glass(
    widget: QWidget,
    radius: float = 18.0,
    top_alpha: int = 165,
    bottom_alpha: int = 195,
    accent_color: QColor | None = None,
    border_color: QColor | None = None,
):
    p = QPainter(widget)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    rect = QRectF(widget.rect()).adjusted(1.5, 1.5, -1.5, -1.5)

    # Fondo cristal oscuro translúcido (#121521 -> #090a0f)
    grad = QLinearGradient(0, rect.top(), 0, rect.bottom())
    grad.setColorAt(0.0, QColor(22, 26, 42, top_alpha))
    grad.setColorAt(0.55, QColor(16, 19, 31, int((top_alpha + bottom_alpha) / 2)))
    grad.setColorAt(1.0, QColor(10, 12, 20, bottom_alpha))
    p.setBrush(grad)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(rect, radius, radius)

    if accent_color is not None:
        radial = QRadialGradient(rect.width() * 0.25, 22, rect.width() * 0.75)
        radial.setColorAt(0.0, accent_color)
        radial.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(radial)
        p.drawRoundedRect(rect, radius, radius)

    # Reflejo superior de cristal
    shine = QLinearGradient(0, rect.top(), 0, rect.top() + min(55.0, rect.height() * 0.38))
    shine.setColorAt(0.0, QColor(255, 255, 255, 28))
    shine.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.setBrush(shine)
    p.drawRoundedRect(rect, radius, radius)

    # Borde luminoso estilo Cloe
    b_col = border_color or QColor(125, 207, 255, 110)
    border = QLinearGradient(0, rect.top(), 0, rect.bottom())
    border.setColorAt(0.0, b_col)
    border.setColorAt(0.5, QColor(77, 88, 133, 95))
    border.setColorAt(1.0, QColor(187, 154, 247, 90))
    p.setPen(QPen(border, 1.5))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(rect, radius, radius)


def make_rounded_pixmap(raw_bytes: bytes, size: int = 58, radius: int = 10) -> QPixmap | None:
    return make_rounded_rect_pixmap(raw_bytes, size, size, radius)


def make_rounded_rect_pixmap(raw_bytes: bytes, width: int = 112, height: int = 86, radius: int = 10) -> QPixmap | None:
    img = QImage.fromData(raw_bytes)
    if img.isNull():
        return None
    scaled = img.scaled(
        width, height,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    out = QPixmap(width, height)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0, 0, width, height, radius, radius)
    p.setClipPath(path)
    x_off = (scaled.width() - width) // 2
    y_off = (scaled.height() - height) // 2
    p.drawImage(-x_off, -y_off, scaled)
    p.end()
    return out


class RandomCatFetcher(QThread):
    """Obtiene un gato aleatorio desde TheCatAPI (usada por https://randomcatapi.netlify.app/)."""

    cat_ready = pyqtSignal(dict)

    def run(self):
        api_url = "https://api.thecatapi.com/v1/images/search"
        try:
            req = urllib.request.Request(api_url, headers={"User-Agent": "CloeAssistant/2.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            if not data or not isinstance(data, list):
                return
            img_url = (data[0].get("url") or "").strip()
            if not img_url:
                return
            img_req = urllib.request.Request(img_url, headers={"User-Agent": "CloeAssistant/2.0"})
            with urllib.request.urlopen(img_req, timeout=6) as img_resp:
                img_bytes = img_resp.read()
            if not img_bytes:
                return
            captions = [
                "¡Mira esto! Mira qué michi me acabo de encontrar ฅ^•ﻌ•^ฅ",
                "(=^･ω･^=) ¡Mira esto! Un michi al azar para alegrarte el rato ✨",
                "¡Mira esto! No pude evitar enseñarte esta fotaza ( =①ω①=)",
                "🐾 ¡Mira esto! Pausa michi obligatoria (=^◡^=)♡",
            ]
            self.cat_ready.emit({
                "kind": "cat_photo",
                "title": "🐾 ¡Mira esto!",
                "subtitle": random.choice(captions),
                "image_bytes": img_bytes,
                "url": img_url,
            })
        except Exception:
            pass


def format_markdown_html(raw: str) -> str:
    """Convierte markdown básico, bloques de código y kaomojis a HTML estilizado."""
    if not raw:
        return ""
    escaped = (
        raw.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    # Bloques de código ```lang ... ```
    def _repl_block(m):
        lang = m.group(1) or "code"
        code = m.group(2).strip("\n")
        return (
            '<div style="margin:6px 0; background-color:rgba(7,8,13,210); '
            'border:1px solid #2a304a; border-radius:8px; padding:6px 8px;">'
            f'<div style="color:#7dcfff; font-size:9.5px; font-family:monospace; margin-bottom:3px;">{lang.upper()}</div>'
            f'<pre style="margin:0; color:#d5dcf9; font-family:\'JetBrains Mono\',monospace; font-size:11px; white-space:pre-wrap;">{code}</pre>'
            "</div>"
        )

    processed = re.sub(r"```([a-zA-Z0-9_-]*)\n([\s\S]*?)(?:```|$)", _repl_block, escaped)
    processed = re.sub(
        r"`([^`\n]+)`",
        r'<code style="background-color:rgba(26,30,46,200); color:#7dcfff; padding:1px 4px; border-radius:4px; font-family:monospace;">\1</code>',
        processed,
    )
    processed = re.sub(r"\*\*([^*]+)\*\*", r'<strong style="color:#ffffff;">\1</strong>', processed)
    processed = re.sub(r"\*([^*]+)\*", r'<em style="color:#7dcfff;">\1</em>', processed)
    processed = processed.replace("\n", "<br>")
    return processed


# ── Buscador de Imágenes y Tarjetas según el Contexto ─────────────────────────
class ContextMediaFetcher(QThread):
    """Obtiene portadas de canciones (iTunes API) o imágenes de contexto (Wikipedia ES)."""

    cards_ready = pyqtSignal(list)

    def __init__(self, user_text: str, reply_text: str):
        super().__init__()
        self.user_text = user_text
        self.reply_text = reply_text

    def run(self):
        cards: list[dict] = []
        try:
            # Solo mostrar tarjetas de canciones si el usuario realmente pidió música
            if is_music_context(self.user_text):
                songs = detect_songs(self.reply_text)
                for song, artist in songs[:3]:
                    card = self._fetch_song_card(song, artist)
                    if card:
                        cards.append(card)
            else:
                topic_card = self._fetch_topic_card(self.user_text, self.reply_text)
                if topic_card:
                    cards.append(topic_card)
        except Exception:
            pass

        self.cards_ready.emit(cards)

    def _fetch_song_card(self, song: str, artist: str) -> dict | None:
        query = f"{song} {artist}".strip()
        url = (
            "https://itunes.apple.com/search?"
            + urllib.parse.urlencode({"term": query, "media": "music", "limit": 1})
        )
        img_bytes = b""
        album_name = ""
        preview_url = ""
        track_title = song
        artist_name = artist
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "CloeAssistant/1.0"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            results = data.get("results") or []
            if results:
                item = results[0]
                track_title = item.get("trackName") or song
                artist_name = item.get("artistName") or artist
                album_name = item.get("collectionName") or ""
                preview_url = item.get("trackViewUrl") or ""
                art_url = (item.get("artworkUrl100") or "").replace("100x100bb", "300x300bb")
                if art_url:
                    with urllib.request.urlopen(art_url, timeout=4) as img_resp:
                        img_bytes = img_resp.read()
        except Exception:
            pass

        search_q = urllib.parse.quote_plus(f"{track_title} {artist_name}".strip())
        open_url = f"https://open.spotify.com/search/{search_q}"
        return {
            "kind": "music",
            "title": f"♪ {track_title}",
            "subtitle": artist_name + (f" · {album_name}" if album_name else ""),
            "image_bytes": img_bytes,
            "query": f"{track_title} {artist_name}".strip(),
            "url": open_url or preview_url,
        }

    def _fetch_topic_card(self, user_text: str, reply_text: str) -> dict | None:
        bolds = re.findall(r"\*\*([^*]{3,35})\*\*", reply_text)
        candidates = bolds + re.findall(r"\b([A-ZÁÉÍÓÚÑ][a-záéíóúñ]{3,25})\b", user_text)
        stop = {"Cloe", "Hola", "Para", "Como", "Cuando", "Porque", "Pero", "Esto", "Tienes", "Puedes"}
        topic = ""
        for c in candidates:
            c_clean = c.strip(".,:;!?¡¿")
            if c_clean not in stop and len(c_clean) >= 4:
                topic = c_clean
                break
        if not topic:
            return None

        api_url = (
            "https://es.wikipedia.org/api/rest_v1/page/summary/"
            + urllib.parse.quote(topic.replace(" ", "_"))
        )
        try:
            req = urllib.request.Request(api_url, headers={"User-Agent": "CloeAssistant/1.0"})
            with urllib.request.urlopen(req, timeout=3.5) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            thumb = (data.get("thumbnail") or {}).get("source")
            extract = (data.get("extract") or "").strip()
            page_url = ((data.get("content_urls") or {}).get("desktop") or {}).get("page") or ""
            if not thumb or not extract:
                return None
            with urllib.request.urlopen(thumb, timeout=3.5) as img_resp:
                img_bytes = img_resp.read()
            return {
                "kind": "topic",
                "title": data.get("title") or topic,
                "subtitle": extract[:120] + ("…" if len(extract) > 120 else ""),
                "image_bytes": img_bytes,
                "url": page_url,
            }
        except Exception:
            return None


# ── Worker con Streaming en Vivo (LLM + Voz en paralelo) ───────────────────────
class CloeWorker(QThread):
    token_received = pyqtSignal(str)
    response_ready = pyqtSignal(str, float, int)  # reply, tok_per_sec, token_count
    speech_finished = pyqtSignal()

    def __init__(
        self,
        client,
        messages,
        tools,
        dispatcher,
        user_input,
        voice_io=None,
        speak_enabled: bool = True,
        conversational: bool = False,
        image_b64: str | None = None,
    ):
        super().__init__()
        self.client = client
        self.messages = messages
        self.tools = tools
        self.dispatcher = dispatcher
        self.user_input = user_input
        self.voice_io = voice_io
        self.speak_enabled = speak_enabled
        self.conversational = conversational
        self.image_b64 = image_b64
        self._aborted = False

    def abort(self):
        self._aborted = True
        if self.voice_io is not None:
            self.voice_io.stop_speaking()

    def run(self):
        speech_stream = None
        t0 = time.monotonic()
        token_count = 0
        try:
            user_msg: dict = {"role": "user", "content": self.user_input}
            if self.image_b64:
                user_msg["image_b64"] = self.image_b64
            self.messages.append(user_msg)
            if self.voice_io is not None and self.speak_enabled:
                speech_stream = self.voice_io.start_stream()

            def on_token(piece: str):
                nonlocal token_count
                if self._aborted:
                    return
                token_count += 1
                self.token_received.emit(piece)
                if speech_stream is not None:
                    speech_stream.feed(piece)

            lower_in = (self.user_input or "").lower()
            is_code_req = any(
                kw in lower_in
                for kw in (
                    "código", "codigo", "script", "función", "funcion", "programa",
                    "python", "javascript", "html", "css", "sql", "bash", "java", "c++",
                )
            )
            max_tokens = 650 if is_code_req else (165 if self.conversational else 260)
            reply = run_tool_loop(
                self.client,
                self.messages,
                self.tools,
                self.dispatcher,
                on_token=on_token,
                num_predict=max_tokens,
            )
            elapsed = max(0.05, time.monotonic() - t0)
            tok_s = max(1, token_count) / elapsed
            self.messages.append({"role": "assistant", "content": reply})
            self.response_ready.emit(reply, tok_s, max(1, token_count))

            if speech_stream is not None and not self._aborted:
                speech_stream.finish(wait=True)
        except Exception as e:
            if speech_stream is not None:
                speech_stream.abort()
            self.response_ready.emit(f"(error: {e})", 0.0, 0)
        finally:
            self.speech_finished.emit()


# ── Hilos de Voz ──────────────────────────────────────────────────────────────
class VoiceLoader(QThread):
    ready = pyqtSignal(object)
    failed = pyqtSignal(str)

    def run(self):
        try:
            from voice import VoiceConfig, VoiceIO
            voice = VoiceIO(VoiceConfig.from_env())
            voice.warmup()
            self.ready.emit(voice)
        except Exception as exc:
            self.failed.emit(str(exc))


class VoiceListenThread(QThread):
    transcribed = pyqtSignal(str)
    level_changed = pyqtSignal(float, str)
    failed = pyqtSignal(str)

    def __init__(self, voice):
        super().__init__()
        self.voice = voice
        self._stop = threading.Event()
        self._cancelled = False

    def finish_recording(self):
        """Detiene la grabación al soltar el círculo y transcribe lo grabado."""
        self._stop.set()

    def cancel(self):
        """Cancela la escucha sin transcribir."""
        self._cancelled = True
        self._stop.set()

    def run(self):
        try:
            def _on_lvl(lvl: float, state: str):
                if not self._cancelled:
                    self.level_changed.emit(lvl, state)

            text = self.voice.listen(on_level=_on_lvl, should_stop=self._stop)
            if not self._cancelled:
                self.transcribed.emit(text or "")
        except Exception as exc:
            if not self._cancelled:
                self.failed.emit(str(exc))


# ── Burbuja de Diálogo Pop-up Unificada al Costado (Basada en mascota_virtual_ia_local_pop_up.html)
class PopupSidePanel(QWidget):
    """
    Única ventana pop-up / panel lateral al costado de Cloe.
    Integra:
    - Modo 1: Burbuja de diálogo actual + tarjetas con imágenes/música según el contexto
    - Modo 2: Cajón de historial completo
    - Chips de sugerencias rápidas, barra de entrada y ajustes de voz integrados
    """

    text_submitted = pyqtSignal(str)
    stop_requested = pyqtSignal()
    clear_requested = pyqtSignal()
    kaomoji_reaction_requested = pyqtSignal()
    song_play_requested = pyqtSignal(str, str)
    visibility_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedWidth(380)
        self.setMinimumHeight(250)
        self.setMaximumHeight(495)
        self.setStyleSheet(GLASS_PANEL_STYLE)

        self._history_mode = False
        self._settings_open = False
        self._state_color = "#7dcfff"

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(7)

        # ── 1. Cabecera Compacta del Pop-up ───────────────────────────────────
        header_frame = QFrame()
        header_frame.setStyleSheet(
            "QFrame { background-color: rgba(26, 30, 46, 155); "
            "border: 1px solid rgba(77, 88, 133, 95); border-radius: 10px; }"
        )
        header = QHBoxLayout(header_frame)
        header.setContentsMargins(9, 5, 7, 5)
        header.setSpacing(4)

        self._state_dot = QLabel("●")
        self._state_dot.setStyleSheet("color: #7dcfff; font-size: 11px; border: none; background: transparent;")
        header.addWidget(self._state_dot)

        self._title_lbl = QLabel("CLOE // ฅ^•ﻌ•^ฅ")
        self._title_lbl.setStyleSheet(
            "color: #7dcfff; font-family: 'JetBrains Mono', monospace; "
            "font-size: 10.5px; font-weight: 700; letter-spacing: 0.6px; border: none; background: transparent;"
        )
        header.addWidget(self._title_lbl, stretch=1)

        # Botón Kaomoji Rápido (=^･^=)
        kao_btn = QPushButton("(=^･^=)")
        kao_btn.setToolTip("Maullido Kaomoji aleatorio")
        kao_btn.setFixedHeight(22)
        kao_btn.setStyleSheet(
            "QPushButton { color: #ff79c6; font-family: 'JetBrains Mono', monospace; "
            "font-size: 10px; padding: 1px 5px; border-radius: 7px; }"
            "QPushButton:hover { border: 1px solid #ff79c6; background-color: rgba(255, 121, 198, 35); }"
        )
        kao_btn.clicked.connect(self.kaomoji_reaction_requested.emit)
        header.addWidget(kao_btn)

        # Alternar entre Vista Burbuja Rápida e Historial Completo
        self._btn_history = QPushButton("💬 Historial")
        self._btn_history.setToolTip("Alternar Historial completo / Burbuja compacta")
        self._btn_history.setFixedHeight(22)
        self._btn_history.setStyleSheet("font-size: 10px; padding: 1px 6px; border-radius: 7px;")
        self._btn_history.clicked.connect(self.toggle_history_mode)
        header.addWidget(self._btn_history)

        # Botón Ajustes de Voz
        cfg_btn = QPushButton("⚙")
        cfg_btn.setToolTip("Configurar Voz y Motor TTS")
        cfg_btn.setFixedSize(22, 22)
        cfg_btn.setStyleSheet("padding: 0px; border-radius: 7px; font-size: 11px;")
        cfg_btn.clicked.connect(self._toggle_settings)
        header.addWidget(cfg_btn)

        # Limpiar memoria
        clr_btn = QPushButton("🗑")
        clr_btn.setToolTip("Limpiar arenero de memoria")
        clr_btn.setFixedSize(22, 22)
        clr_btn.setStyleSheet(
            "QPushButton { padding: 0px; border-radius: 7px; font-size: 10.5px; }"
            "QPushButton:hover { border: 1px solid #f7768e; color: #f7768e; }"
        )
        clr_btn.clicked.connect(self.clear_requested.emit)
        header.addWidget(clr_btn)

        # Minimizar Burbuja (Deja solo a Cloe)
        min_btn = QPushButton("—")
        min_btn.setToolTip("Ocultar burbuja (deja solo a Cloe)")
        min_btn.setFixedSize(22, 22)
        min_btn.setStyleSheet("padding: 0px; border-radius: 7px; font-size: 11px;")
        min_btn.clicked.connect(lambda: self.set_bubble_visible(False))
        header.addWidget(min_btn)

        root.addWidget(header_frame)

        # ── 2. MODO 1: Burbuja de Diálogo Actual (Compacta + Imágenes de Contexto)
        self._single_view = QWidget()
        self._single_view.setStyleSheet("background: transparent;")
        sv_layout = QVBoxLayout(self._single_view)
        sv_layout.setContentsMargins(2, 2, 2, 2)
        sv_layout.setSpacing(6)

        self._user_pill = QLabel("")
        self._user_pill.setWordWrap(True)
        self._user_pill.setStyleSheet(
            "background-color: rgba(26, 30, 46, 175); color: #bb9af7; "
            "border: 1px solid rgba(187, 154, 247, 65); border-radius: 8px; "
            "padding: 4px 8px; font-family: 'JetBrains Mono', monospace; font-size: 11px;"
        )
        self._user_pill.hide()
        sv_layout.addWidget(self._user_pill)

        self._single_reply = QTextEdit()
        self._single_reply.setReadOnly(True)
        self._single_reply.setFrameShape(QFrame.Shape.NoFrame)
        self._single_reply.setMinimumHeight(92)
        self._single_reply.setMaximumHeight(185)
        self._single_reply.setHtml(
            '<span style="color:#7dcfff; font-family:monospace; font-weight:700;">(=^･ω･^=) ¡Michi-saludos!</span> '
            "Soy <b>Cloe</b> <code>ฅ^•ﻌ•^ฅ</code>. "
            "Mantén presionado mi círculo para hablarme por voz, haz doble clic para charla continua "
            "o escríbeme aquí. <span style=\"color:#ff79c6; font-family:monospace;\">( =①ω①=)</span>"
        )
        sv_layout.addWidget(self._single_reply)

        # Tarjetas contextuales con imágenes (álbumes de Spotify/iTunes o Wikipedia)
        self._cards_scroll = QScrollArea()
        self._cards_scroll.setWidgetResizable(True)
        self._cards_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._cards_container = QWidget()
        self._cards_container.setStyleSheet("background: transparent;")
        self._cards_layout = QVBoxLayout(self._cards_container)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(5)
        self._cards_scroll.setWidget(self._cards_container)
        self._cards_scroll.hide()
        sv_layout.addWidget(self._cards_scroll)

        self._metrics_lbl = QLabel("")
        self._metrics_lbl.setStyleSheet(
            "color: #6b759e; font-family: 'JetBrains Mono', monospace; font-size: 10px; background: transparent;"
        )
        self._metrics_lbl.hide()
        sv_layout.addWidget(self._metrics_lbl)

        root.addWidget(self._single_view)

        # ── 3. MODO 2: Cajón de Historial Completo (Oculto por defecto) ───────
        self._history_view = QTextEdit()
        self._history_view.setReadOnly(True)
        self._history_view.setFrameShape(QFrame.Shape.NoFrame)
        self._history_view.setMinimumHeight(180)
        self._history_view.setMaximumHeight(260)
        self._history_view.hide()
        root.addWidget(self._history_view)

        # ── 4. Cajón de Ajustes de IA y Voz (Integrado en la misma burbuja) ───
        self._settings_panel = QFrame()
        self._settings_panel.setStyleSheet(
            "QFrame { background-color: rgba(14, 16, 28, 195); "
            "border: 1px solid rgba(125, 207, 255, 75); border-radius: 12px; }"
            "QLabel { background: transparent; border: none; font-size: 11px; color: #d5dcf9; }"
        )
        sp = QVBoxLayout(self._settings_panel)
        sp.setContentsMargins(9, 7, 9, 7)
        sp.setSpacing(5)

        row_llm = QHBoxLayout()
        row_llm.addWidget(QLabel("Cerebro IA:"))
        self.llm_combo = QComboBox()
        self.llm_combo.addItem("Auto (Nube Gratis → Local)", "auto")
        self.llm_combo.addItem("Groq · Llama 3.3 70B (0% GPU)", "groq")
        self.llm_combo.addItem("Gemini · 2.5 Flash (0% GPU)", "gemini")
        self.llm_combo.addItem("Ollama Local (cloe)", "ollama")
        row_llm.addWidget(self.llm_combo, stretch=1)
        sp.addLayout(row_llm)

        row_key = QHBoxLayout()
        row_key.setSpacing(4)
        self.api_key_field = QLineEdit()
        self.api_key_field.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_field.setPlaceholderText("Pega tu API Key de Groq (gsk_...) o Gemini (AIza...)")
        self.api_key_field.setStyleSheet("font-size: 10.5px; padding: 3px 7px; border-radius: 7px;")
        row_key.addWidget(self.api_key_field, stretch=1)

        self.btn_save_key = QPushButton("Guardar Key")
        self.btn_save_key.setFixedHeight(23)
        self.btn_save_key.setStyleSheet(
            "QPushButton { font-size: 10px; padding: 2px 7px; border-radius: 7px; "
            "border: 1px solid #9ece6a; color: #9ece6a; background-color: rgba(158, 206, 106, 35); }"
            "QPushButton:hover { background-color: rgba(158, 206, 106, 85); color: #ffffff; }"
        )
        row_key.addWidget(self.btn_save_key)
        sp.addLayout(row_key)

        row_eng = QHBoxLayout()
        row_eng.addWidget(QLabel("Motor Voz:"))
        self.engine_combo = QComboBox()
        self.engine_combo.addItems(["edge", "kokoro", "piper", "espeak", "none"])
        row_eng.addWidget(self.engine_combo, stretch=1)
        sp.addLayout(row_eng)

        row_voice = QHBoxLayout()
        row_voice.addWidget(QLabel("Timbre:"))
        self.voice_combo = QComboBox()
        row_voice.addWidget(self.voice_combo, stretch=1)
        sp.addLayout(row_voice)

        row_spd = QHBoxLayout()
        self.speed_label = QLabel("Ritmo: 1.08x")
        row_spd.addWidget(self.speed_label)
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setRange(85, 135)
        self.speed_slider.setValue(108)
        row_spd.addWidget(self.speed_slider, stretch=1)
        sp.addLayout(row_spd)

        self._settings_panel.hide()
        root.addWidget(self._settings_panel)

        # ── 5. Chips de Sugerencias Rápidas Michi (Cloe) ──────────────────────
        chips_row = QHBoxLayout()
        chips_row.setContentsMargins(0, 0, 0, 0)
        chips_row.setSpacing(3)
        quick_prompts = [
            ("👁️ Pantalla", "Cloe, mira mi pantalla y dime qué estoy viendo o ayúdame con esto."),
            ("📋 Copiado", "Cloe, explica o resume lo que acabo de copiar en el portapapeles."),
            ("⛅ Clima", "Cloe, ¿cómo está el clima hoy y qué temperatura hace?"),
            ("💻 Mi PC", "Cloe, dime cómo está el estado de mi PC (batería, RAM y espacio libre en disco)."),
            ("🍅 Pomodoro", "Cloe, pon un pomodoro de 25 minutos para concentrarme."),
        ]
        for label, prompt_txt in quick_prompts:
            chip = QPushButton(label)
            chip.setFixedHeight(22)
            chip.setStyleSheet(
                "QPushButton { font-family: 'Inter', 'Segoe UI', sans-serif; font-size: 9px; "
                "padding: 1px 4px; border-radius: 10px; background-color: rgba(26, 30, 46, 150); "
                "color: #9aa5ce; }"
                "QPushButton:hover { color: #7dcfff; border: 1px solid #7dcfff; }"
            )
            chip.clicked.connect(lambda _, p=prompt_txt: self.text_submitted.emit(p))
            chips_row.addWidget(chip)
        root.addLayout(chips_row)

        # ── 6. Barra de Entrada Rápida ────────────────────────────────────────
        input_row = QHBoxLayout()
        input_row.setSpacing(6)

        self._field = QLineEdit()
        self._field.setPlaceholderText("Maúllale algo a Cloe... (=^･ｪ･^=)")
        self._field.returnPressed.connect(self._on_send)
        input_row.addWidget(self._field, stretch=1)

        self._btn_stop = QPushButton("⏹")
        self._btn_stop.setToolTip("Detener respuesta (Esc)")
        self._btn_stop.setFixedSize(28, 28)
        self._btn_stop.setStyleSheet(
            "QPushButton { background-color: rgba(247, 118, 142, 45); "
            "border: 1px solid rgba(247, 118, 142, 140); color: #f7768e; border-radius: 9px; padding: 0px; }"
            "QPushButton:hover { background-color: rgba(247, 118, 142, 85); }"
        )
        self._btn_stop.clicked.connect(self.stop_requested.emit)
        self._btn_stop.hide()
        input_row.addWidget(self._btn_stop)

        self._btn_send = QPushButton("➤")
        self._btn_send.setToolTip("Enviar (Enter)")
        self._btn_send.setFixedSize(28, 28)
        self._btn_send.setStyleSheet(
            "QPushButton { background-color: rgba(125, 207, 255, 45); "
            "border: 1px solid rgba(125, 207, 255, 130); color: #7dcfff; border-radius: 9px; padding: 0px; }"
            "QPushButton:hover { background-color: rgba(125, 207, 255, 85); color: #ffffff; }"
        )
        self._btn_send.clicked.connect(self._on_send)
        input_row.addWidget(self._btn_send)

        root.addLayout(input_row)

    def set_state_badge(self, state: str):
        colors = {
            "idle": "#7dcfff",
            "listening": "#9ece6a",
            "thinking": "#bb9af7",
            "speaking": "#ff79c6",
            "happy": "#ff79c6",
            "laser": "#f7768e",
            "sleeping": "#6b759e",
        }
        col = colors.get(state, "#7dcfff")
        self._state_color = col
        self._state_dot.setStyleSheet(f"color: {col}; font-size: 11px; border: none; background: transparent;")
        self.update()

    def set_generating(self, generating: bool):
        self._btn_send.setVisible(not generating)
        self._btn_stop.setVisible(generating)

    def _recalc_size_and_notify(self):
        if self.layout() is not None:
            self.layout().activate()
        self.updateGeometry()
        self.adjustSize()
        pw = self.parentWidget()
        if pw is not None and pw.layout() is not None:
            pw.layout().activate()
        self.visibility_changed.emit()
        QTimer.singleShot(0, self.visibility_changed.emit)
        QTimer.singleShot(30, self.visibility_changed.emit)

    def set_bubble_visible(self, visible: bool):
        self.setVisible(visible)
        self._recalc_size_and_notify()

    def toggle_history_mode(self):
        self._history_mode = not self._history_mode
        self._single_view.setVisible(not self._history_mode)
        self._history_view.setVisible(self._history_mode)
        self._btn_history.setText("💬 Burbuja" if self._history_mode else "💬 Historial")
        if self._history_mode:
            sb = self._history_view.verticalScrollBar()
            sb.setValue(sb.maximum())
        self._recalc_size_and_notify()

    def _toggle_settings(self):
        self._settings_open = not self._settings_open
        self._settings_panel.setVisible(self._settings_open)
        self._single_reply.setMaximumHeight(115 if self._settings_open else 185)
        self._recalc_size_and_notify()

    def _on_send(self):
        txt = self._field.text().strip()
        if not txt:
            return
        self._field.clear()
        self.text_submitted.emit(txt)

    def update_single_exchange(
        self,
        user_text: str | None,
        reply_text: str,
        streaming: bool = False,
        metrics: str | None = None,
    ):
        if user_text:
            short_u = user_text if len(user_text) <= 68 else user_text[:65] + "…"
            self._user_pill.setText(f"tú: {short_u}")
            self._user_pill.show()
        html = format_markdown_html(reply_text)
        if streaming:
            html += ' <span style="color:#7dcfff; font-weight:bold;">▋</span>'
        self._single_reply.setHtml(html)
        sb = self._single_reply.verticalScrollBar()
        sb.setValue(sb.maximum())

        if metrics:
            self._metrics_lbl.setText(metrics)
            self._metrics_lbl.show()
        elif streaming:
            self._metrics_lbl.hide()

        self._recalc_size_and_notify()

    def set_cards(self, cards: list[dict]):
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not cards:
            self._cards_scroll.hide()
            self._recalc_size_and_notify()
            return

        has_cat_photo = False
        for card in cards:
            kind = card.get("kind", "")
            is_cat = kind == "cat_photo"
            is_term_confirm = kind == "terminal_confirm"
            is_term_result = kind == "terminal_result"
            if is_cat:
                has_cat_photo = True
            frame = QFrame()
            if is_term_confirm:
                border_c = "rgba(224, 175, 104, 140)"
            elif is_term_result:
                border_c = "rgba(158, 206, 106, 110)"
            elif is_cat:
                border_c = "rgba(255, 121, 198, 95)"
            else:
                border_c = "rgba(125, 207, 255, 65)"
            frame.setStyleSheet(
                f"QFrame {{ background-color: rgba(26, 30, 46, 185); "
                f"border: 1px solid {border_c}; border-radius: 12px; }}"
                "QLabel { background: transparent; border: none; }"
            )
            row = QHBoxLayout(frame)
            row.setContentsMargins(7, 6, 8, 6)
            row.setSpacing(9)

            img_lbl = QLabel()
            if is_cat:
                img_lbl.setFixedSize(112, 86)
                pix = make_rounded_rect_pixmap(card.get("image_bytes", b""), width=112, height=86, radius=10)
            else:
                img_lbl.setFixedSize(44, 44)
                pix = make_rounded_pixmap(card.get("image_bytes", b""), size=44, radius=9)

            if pix is not None:
                img_lbl.setPixmap(pix)
            else:
                if kind == "music":
                    icon_txt = "🎵"
                elif is_term_confirm:
                    icon_txt = "🛡️"
                elif is_term_result:
                    icon_txt = "💻"
                elif is_cat:
                    icon_txt = "🐱"
                else:
                    icon_txt = "✨"
                img_lbl.setText(icon_txt)
                img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                img_lbl.setStyleSheet(
                    "background-color: rgba(125, 207, 255, 35); border-radius: 9px; font-size: 19px;"
                )
            row.addWidget(img_lbl)

            info_col = QVBoxLayout()
            info_col.setSpacing(2)
            t_lbl = QLabel(card.get("title", ""))
            t_lbl.setWordWrap(True)
            t_col = "#e0af68" if is_term_confirm else ("#ff79c6" if is_cat else "#ffffff")
            t_lbl.setStyleSheet(f"color: {t_col}; font-size: 11px; font-weight: 700;")
            s_lbl = QLabel(card.get("subtitle", ""))
            s_lbl.setWordWrap(True)
            s_lbl.setStyleSheet("color: #d5dcf9; font-size: 10px;" if (is_cat or is_term_confirm or is_term_result) else "color: #9aa5ce; font-size: 10.5px;")
            info_col.addWidget(t_lbl)
            info_col.addWidget(s_lbl)
            row.addLayout(info_col, stretch=1)

            if is_term_confirm:
                btn_col = QVBoxLayout()
                btn_col.setSpacing(3)
                ok_btn = QPushButton("✅ Autorizar")
                ok_btn.setFixedHeight(22)
                ok_btn.setStyleSheet(
                    "QPushButton { background-color: rgba(158, 206, 106, 65); "
                    "border: 1px solid #9ece6a; color: #9ece6a; border-radius: 7px; font-weight: 700; font-size: 10px; padding: 0 7px; }"
                    "QPushButton:hover { background-color: rgba(158, 206, 106, 130); color: #ffffff; }"
                )
                ok_btn.clicked.connect(lambda: self.text_submitted.emit("autorizo el comando"))
                cancel_btn = QPushButton("❌ Cancelar")
                cancel_btn.setFixedHeight(22)
                cancel_btn.setStyleSheet(
                    "QPushButton { background-color: rgba(247, 118, 142, 55); "
                    "border: 1px solid #f7768e; color: #f7768e; border-radius: 7px; font-weight: 600; font-size: 10px; padding: 0 7px; }"
                    "QPushButton:hover { background-color: rgba(247, 118, 142, 120); color: #ffffff; }"
                )
                cancel_btn.clicked.connect(lambda: self.text_submitted.emit("cancelar comando"))
                btn_col.addWidget(ok_btn)
                btn_col.addWidget(cancel_btn)
                row.addLayout(btn_col)
            elif kind == "music":
                play_btn = QPushButton("▶ Spotify")
                play_btn.setFixedHeight(24)
                play_btn.setStyleSheet(
                    "QPushButton { background-color: rgba(158, 206, 106, 55); "
                    "border: 1px solid #9ece6a; color: #9ece6a; border-radius: 8px; font-weight: 600; font-size: 10px; }"
                    "QPushButton:hover { background-color: rgba(158, 206, 106, 110); color: #ffffff; }"
                )
                q = card.get("query", "")
                u = card.get("url", "")
                play_btn.clicked.connect(lambda _, q=q, u=u: self.song_play_requested.emit(q, u))
                row.addWidget(play_btn)
            elif card.get("url"):
                open_btn = QPushButton("Ver")
                open_btn.setFixedHeight(24)
                u = card["url"]
                open_btn.clicked.connect(lambda _, u=u: QDesktopServices.openUrl(QUrl(u)))
                row.addWidget(open_btn)

            self._cards_layout.addWidget(frame)

        card_h = 104 if has_cat_photo else min(145, 74 * len(cards))
        self._cards_scroll.setFixedHeight(card_h)
        self._cards_scroll.show()
        self._recalc_size_and_notify()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.visibility_changed.emit()

    def moveEvent(self, event):
        super().moveEvent(event)
        self.visibility_changed.emit()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            win = self.window()
            if hasattr(win, "begin_panel_drag"):
                win.begin_panel_drag(event.globalPosition().toPoint())
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            win = self.window()
            if hasattr(win, "update_panel_drag"):
                win.update_panel_drag(event.globalPosition().toPoint())
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            win = self.window()
            if hasattr(win, "end_panel_drag"):
                win.end_panel_drag()
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def paintEvent(self, _):
        paint_frosted_glass(
            self,
            radius=18.0,
            top_alpha=185,
            bottom_alpha=210,
            accent_color=QColor(125, 207, 255, 26),
            border_color=QColor(self._state_color),
        )


# ── Mascota Virtual + Círculo de Cristal (Sprite Pixel-Art 16x16 + Kaomojis) ──
class NekoOrbWidget(QWidget):
    """
    Círculo de cristal que muestra a Cloe en Pixel-Art 16x16
    con su píldora de Kaomoji sobre las orejas, partículas flotantes y anillo de voz.
    """

    WIDTH = 148
    HEIGHT = 152

    def __init__(self, controller: "CloePet"):
        super().__init__(controller)
        self._ctrl = controller
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(
            "Cloe ฅ^•ﻌ•^ฅ\n"
            "• Mantén presionado 1 vez para hablar (suelta para enviar)\n"
            "• Doble clic para charla continua manos libres\n"
            "• Clic corto para acariciar (ronroneo)\n"
            "• Arrastra para moverla por tu escritorio"
        )
        self._tick = 0
        self._particles: list[dict] = []
        self._laser = {"x": 28.0, "y": 92.0, "vx": 2.3, "vy": 1.4}

        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._step_animation)
        self._anim_timer.start(35)

    def spawn_particles(self, p_type: str, count: int = 4):
        for _ in range(count):
            self._particles.append({
                "x": self.WIDTH / 2.0 + random.uniform(-26, 26),
                "y": 58.0 + random.uniform(-12, 12),
                "vx": random.uniform(-0.8, 0.8),
                "vy": random.uniform(-1.2, -0.55),
                "life": 1.0,
                "type": p_type,
            })

    def _step_animation(self):
        self._tick += 1
        c = self._ctrl

        if c._state_mode == "sleeping" and self._tick % 55 == 0:
            self.spawn_particles("zZz", 1)
        elif c._state_mode == "thinking" and self._tick % 32 == 0:
            self.spawn_particles("nya?", 1)
        elif c._state_mode == "laser":
            ld = self._laser
            ld["x"] += ld["vx"]
            ld["y"] += ld["vy"]
            if ld["x"] < 34 or ld["x"] > self.WIDTH - 34:
                ld["vx"] *= -1
            if ld["y"] < 72 or ld["y"] > 122:
                ld["vy"] *= -1

        for i in range(len(self._particles) - 1, -1, -1):
            pt = self._particles[i]
            pt["x"] += pt["vx"]
            pt["y"] += pt["vy"]
            pt["life"] -= 0.028
            if pt["life"] <= 0:
                self._particles.pop(i)

        self.update()

    def paintEvent(self, _):
        c = self._ctrl
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        cx = self.width() / 2.0
        cy = 90.0
        base_r = 50.0

        # ── 1. Píldora de Kaomoji Flotante sobre las orejas ───────────────────
        pill_w = 138.0
        pill_h = 24.0
        pill_rect = QRectF(cx - pill_w / 2.0, 2.0, pill_w, pill_h)

        p.setBrush(QColor(18, 21, 33, 230))
        border_col = {
            "listening": QColor("#9ece6a"),
            "thinking": QColor("#bb9af7"),
            "speaking": QColor("#ff79c6"),
            "happy": QColor("#ff79c6"),
            "laser": QColor("#f7768e"),
            "sleeping": QColor("#6b759e"),
        }.get(c._state_mode, QColor("#4d5885"))
        p.setPen(QPen(border_col, 1.3))
        p.drawRoundedRect(pill_rect, 12.0, 12.0)

        p.setFont(QFont("JetBrains Mono", 9, QFont.Weight.Bold))
        p.setPen(QColor("#7dcfff") if c._state_mode == "idle" else border_col)
        pill_txt = f"{c._emote_icon} {c._face}"
        p.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, pill_txt)

        # ── 2. Halo reactivo + Círculo de Cristal ─────────────────────────────
        if c._state_mode == "listening":
            dyn = min(8.0, c._mic_level * 95.0) + 3.0 * c._pulse_phase
            halo_col = QColor(158, 206, 106, int(85 + 65 * c._pulse_phase))
            rim_col = QColor(158, 206, 106, 225)
        elif c._state_mode == "speaking":
            dyn = 5.0 * c._pulse_phase
            halo_col = QColor(255, 121, 198, int(85 + 65 * c._pulse_phase))
            rim_col = QColor(255, 121, 198, 225)
        elif c._state_mode == "thinking":
            dyn = 3.5 * c._pulse_phase
            halo_col = QColor(187, 154, 247, int(80 + 55 * c._pulse_phase))
            rim_col = QColor(187, 154, 247, 215)
        elif c._state_mode == "laser":
            dyn = 4.0 * c._pulse_phase
            halo_col = QColor(247, 118, 142, 115)
            rim_col = QColor(247, 118, 142, 225)
        else:
            dyn = 2.0 * c._pulse_phase
            halo_col = QColor(125, 207, 255, int(40 + 25 * c._pulse_phase))
            rim_col = QColor(125, 207, 255, 135)

        halo_grad = QRadialGradient(cx, cy, base_r + 8.0 + dyn)
        halo_grad.setColorAt(0.6, halo_col)
        halo_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(halo_grad)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPoint(int(cx), int(cy)), int(base_r + 8 + dyn), int(base_r + 8 + dyn))

        orb_rect = QRectF(cx - base_r, cy - base_r, base_r * 2, base_r * 2)
        glass_grad = QLinearGradient(orb_rect.left(), orb_rect.top(), orb_rect.left(), orb_rect.bottom())
        glass_grad.setColorAt(0.0, QColor(28, 33, 52, 140))
        glass_grad.setColorAt(0.6, QColor(16, 19, 31, 160))
        glass_grad.setColorAt(1.0, QColor(10, 12, 20, 180))
        p.setBrush(glass_grad)
        p.drawEllipse(orb_rect)

        # Brillo superior del cristal
        shine_rect = QRectF(cx - base_r * 0.76, cy - base_r * 0.88, base_r * 1.52, base_r * 0.9)
        shine_grad = QLinearGradient(0, shine_rect.top(), 0, shine_rect.bottom())
        shine_grad.setColorAt(0.0, QColor(255, 255, 255, 52))
        shine_grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setBrush(shine_grad)
        p.drawEllipse(shine_rect)

        p.setPen(QPen(rim_col, 2.0 if c._state_mode != "idle" else 1.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(orb_rect)

        # Arco luminoso de cuenta regresiva (Recordatorio / Pomodoro activo)
        rem_sec = max(0.0, getattr(c, "_timer_end_time", 0.0) - time.monotonic())
        tot_sec = max(1.0, getattr(c, "_timer_total_s", 1.0))
        if rem_sec > 0.0:
            ratio = max(0.02, min(1.0, rem_sec / tot_sec))
            arc_col = QColor("#ff79c6") if getattr(c, "_timer_kind", "") == "pomodoro" else QColor("#e0af68")
            arc_pen = QPen(arc_col, 3.0)
            arc_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(arc_pen)
            arc_rect = orb_rect.adjusted(-3.5, -3.5, 3.5, 3.5)
            p.drawArc(arc_rect, 90 * 16, int(-ratio * 360 * 16))

        # ── 3. Dibujar Sprite Pixel-Art 16x16 de Cloe ─────────────────────────
        tail_swing = (self._tick // 18) % 2 == 0
        sprite = NEKO_IDLE_1 if tail_swing else NEKO_IDLE_2
        if c._state_mode == "sleeping":
            sprite = NEKO_SLEEP
        elif c._state_mode == "happy":
            sprite = NEKO_HAPPY
        elif c._state_mode == "laser":
            sprite = NEKO_TALK if (self._tick // 5) % 2 == 0 else NEKO_IDLE_1
        elif c._state_mode == "speaking":
            mouth_open = (self._tick // 4) % 2 == 0
            sprite = NEKO_TALK if mouth_open else (NEKO_IDLE_1 if tail_swing else NEKO_IDLE_2)
        elif c._state_mode in ("thinking", "listening"):
            sprite = NEKO_IDLE_1 if (self._tick // 10) % 2 == 0 else NEKO_IDLE_2
        else:
            if self._tick % 110 > 103:
                sprite = NEKO_BLINK

        bob = 0
        shake_x = 0
        if c._state_mode in ("thinking", "listening"):
            bob = int(round(math.sin(self._tick * 0.24) * 2.5))
        elif c._state_mode == "happy":
            bob = int(round(abs(math.sin(self._tick * 0.22)) * -4.0))
            shake_x = 1 if (self._tick % 4 < 2) else -1
        elif c._state_mode == "laser":
            bob = int(round(abs(math.sin(self._tick * 0.38)) * -6.0))
            shake_x = int(round(math.sin(self._tick * 0.28) * 4.0))
        elif c._state_mode == "sleeping":
            bob = int(round(math.sin(self._tick * 0.06) * 1.5))
        else:
            bob = int(round(math.sin(self._tick * 0.09) * 2.0))

        # Sombra bajo las patitas
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 95))
        p.drawRoundedRect(QRectF(cx - 22, cy + 26, 44, 5), 2.5, 2.5)

        scale = 4
        start_x = int(cx - (16 * scale) / 2) + shake_x
        start_y = int(cy - (16 * scale) / 2) - 2 + bob
        palette = get_palette_for_state(c._state_mode)

        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        for r in range(16):
            row_str = sprite[r]
            for col_idx in range(16):
                ch = row_str[col_idx]
                if ch != "." and ch in palette:
                    p.fillRect(
                        start_x + col_idx * scale,
                        start_y + r * scale,
                        scale,
                        scale,
                        QColor(palette[ch]),
                    )

        # Punto rojo del puntero láser
        if c._state_mode == "laser":
            lx = int(self._laser["x"])
            ly = int(self._laser["y"])
            p.fillRect(lx, ly, 5, 5, QColor("#ff2e55"))
            p.fillRect(lx + 1, ly + 1, 2, 2, QColor("#ffffff"))

        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # ── 4. Etiqueta de modo voz / temporizador en la base del círculo ─────
        if rem_sec > 0.0 and c._state_mode == "idle":
            mins_rem = int(rem_sec) // 60
            secs_rem = int(rem_sec) % 60
            icon_t = "🍅" if getattr(c, "_timer_kind", "") == "pomodoro" else "⏳"
            status_txt = f"{icon_t} {mins_rem:02d}:{secs_rem:02d}"
        elif getattr(c, "_sleeping", False) or c._state_mode == "sleeping":
            status_txt = "zZz siesta"
        else:
            status_txt = {
                "listening": "● escuchando",
                "thinking": "… pensando",
                "speaking": "♪ hablando",
                "sleeping": "zZz siesta",
                "laser": "⚡ láser",
                "happy": "♥ nyaa~",
                "idle": "∞ continua" if c._conversation_mode else "● cloe",
            }.get(c._state_mode, "● cloe")

        p.setFont(QFont("JetBrains Mono", 7, QFont.Weight.Bold))
        p.setPen(rim_col)
        p.drawText(QRectF(cx - 46, cy + base_r - 16, 92, 14), Qt.AlignmentFlag.AlignCenter, status_txt)

        # ── 5. Partículas Flotantes (♥, nya~, zZz, +ATÚN) ─────────────────────
        p.setFont(QFont("JetBrains Mono", 8, QFont.Weight.Bold))
        for pt in self._particles:
            alpha = max(0, min(255, int(pt["life"] * 255)))
            t = pt["type"]
            if t in ("♥", "nya~"):
                col = QColor(255, 121, 198, alpha)
            elif t == "zZz":
                col = QColor(125, 207, 255, alpha)
            elif t == "+ATÚN":
                col = QColor(158, 206, 106, alpha)
            else:
                col = QColor(224, 175, 104, alpha)
            p.setPen(col)
            p.drawText(int(pt["x"]), int(pt["y"]), t)

    def mousePressEvent(self, event):
        self._ctrl.orb_mouse_press(event)

    def mouseMoveEvent(self, event):
        self._ctrl.orb_mouse_move(event)

    def mouseReleaseEvent(self, event):
        self._ctrl.orb_mouse_release(event)

    def mouseDoubleClickEvent(self, event):
        self._ctrl.orb_mouse_double_click(event)


# ── Dock de Acciones Felinas debajo del Sprite (de mascota_virtual_ia_local_pop_up.html)
class PetDockWidget(QFrame):
    """Barra inferior redondeada con acciones felinas, Pomodoro, Dormir/No Molestar, control de voz y burbuja."""

    def __init__(self, controller: "CloePet"):
        super().__init__(controller)
        self._ctrl = controller
        self.setFixedSize(162, 32)
        self.setStyleSheet(
            "QFrame { background-color: rgba(18, 21, 33, 225); "
            "border: 1px solid #2a304a; border-radius: 16px; }"
            "QPushButton { background: transparent; border: none; border-radius: 10px; "
            "padding: 0px; font-size: 12px; color: #9aa5ce; }"
            "QPushButton:hover { background-color: rgba(125, 207, 255, 38); color: #ffffff; }"
        )

        row = QHBoxLayout(self)
        row.setContentsMargins(6, 3, 6, 3)
        row.setSpacing(2)

        btn_love = QPushButton("♥")
        btn_love.setToolTip("Acariciar lomo (Ronroneo ฅ^•ﻌ•^ฅ)")
        btn_love.setFixedSize(22, 22)
        btn_love.setStyleSheet("QPushButton:hover { color: #ff79c6; background-color: rgba(255,121,198,35); }")
        btn_love.clicked.connect(lambda: self._ctrl.pet_action("love"))
        row.addWidget(btn_love)

        btn_feed = QPushButton("🐟")
        btn_feed.setToolTip("Dar Cyber-Atún (+RAM 🐟)")
        btn_feed.setFixedSize(22, 22)
        btn_feed.clicked.connect(lambda: self._ctrl.pet_action("feed"))
        row.addWidget(btn_feed)

        self.btn_pomodoro = QPushButton("🍅")
        self.btn_pomodoro.setToolTip("Iniciar / Cancelar Pomodoro de 25 min 🍅")
        self.btn_pomodoro.setFixedSize(22, 22)
        self.btn_pomodoro.clicked.connect(lambda: self._ctrl.pet_action("pomodoro"))
        row.addWidget(self.btn_pomodoro)

        self.btn_sleep = QPushButton("🌙")
        self.btn_sleep.setToolTip("Dormir / No Molestar ( -ω-): Cloe no realiza nada sola")
        self.btn_sleep.setFixedSize(22, 22)
        self.btn_sleep.clicked.connect(lambda: self._ctrl.pet_action("sleep"))
        row.addWidget(self.btn_sleep)

        self.btn_voice = QPushButton("🔊")
        self.btn_voice.setToolTip("Voz de Cloe ON/OFF")
        self.btn_voice.setFixedSize(22, 22)
        self.btn_voice.clicked.connect(self._ctrl.toggle_voice_button)
        row.addWidget(self.btn_voice)

        self.btn_bubble = QPushButton("💬")
        self.btn_bubble.setToolTip("Mostrar / Ocultar Burbuja al costado")
        self.btn_bubble.setFixedSize(22, 22)
        self.btn_bubble.clicked.connect(self._ctrl.toggle_bubble)
        row.addWidget(self.btn_bubble)

    def set_pomodoro_active(self, active: bool):
        if active:
            self.btn_pomodoro.setStyleSheet(
                "QPushButton { background-color: rgba(255, 121, 198, 75); "
                "border: 1px solid #ff79c6; color: #ffffff; border-radius: 10px; }"
            )
            self.btn_pomodoro.setToolTip("🍅 Pomodoro ACTIVO (clic para cancelar)")
        else:
            self.btn_pomodoro.setStyleSheet("")
            self.btn_pomodoro.setToolTip("Iniciar / Cancelar Pomodoro de 25 min 🍅")

    def set_sleep_active(self, active: bool):
        if active:
            self.btn_sleep.setStyleSheet(
                "QPushButton { background-color: rgba(187, 154, 247, 75); "
                "border: 1px solid #bb9af7; color: #ffffff; border-radius: 10px; }"
            )
            self.btn_sleep.setToolTip("🌙 Modo Siesta / No Molestar ACTIVO (clic para despertar)")
        else:
            self.btn_sleep.setStyleSheet("")
            self.btn_sleep.setToolTip("Dormir / No Molestar ( -ω-): Cloe no realiza nada sola")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._ctrl.begin_panel_drag(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._ctrl.update_panel_drag(event.globalPosition().toPoint())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._ctrl.end_panel_drag()


# ── Indicador de Consumo de Recursos (GPU, RAM, CPU) debajo del Gato ──────────
class PetStatsBar(QFrame):
    """Píldora compacta debajo de Cloe que muestra consumo de recursos en vivo (GPU %, RAM MB, CPU %)."""

    def __init__(self, controller: "CloePet"):
        super().__init__(controller)
        self._ctrl = controller
        self.setFixedSize(166, 22)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setStyleSheet(
            "QFrame { background-color: rgba(18, 21, 33, 225); "
            "border: 1px solid #2a304a; border-radius: 11px; }"
            "QLabel { background: transparent; border: none; "
            "font-family: 'JetBrains Mono', monospace; font-size: 9px; font-weight: 600; }"
        )
        self.setToolTip("Consumo de recursos en vivo: GPU % · RAM MB · CPU % (arrastra para mover)")

        row = QHBoxLayout(self)
        row.setContentsMargins(7, 2, 7, 2)
        row.setSpacing(5)

        self.lbl_gpu = QLabel('<span style="color:#ff79c6;">GPU</span> <span style="color:#d5dcf9;">0%</span>')
        self.lbl_ram = QLabel('<span style="color:#9ece6a;">🐟</span> <span style="color:#d5dcf9;">64MB</span>')
        self.lbl_cpu = QLabel('<span style="color:#7dcfff;">⚡</span> <span style="color:#d5dcf9;">2%</span>')
        for lbl in (self.lbl_gpu, self.lbl_ram, self.lbl_cpu):
            lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        row.addWidget(self.lbl_gpu)
        row.addStretch(1)
        row.addWidget(self.lbl_ram)
        row.addStretch(1)
        row.addWidget(self.lbl_cpu)

        self._prev_idle = 0
        self._prev_total = 0
        self.gpu_pct = 0
        self._gpu_polling = False
        self.purr_pct = 90
        self.bonus_atun_mb = 0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh_stats)
        self._timer.start(2000)
        self.refresh_stats()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._ctrl.begin_panel_drag(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._ctrl.update_panel_drag(event.globalPosition().toPoint())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._ctrl.end_panel_drag()

    def _poll_gpu_async(self):
        if self._gpu_polling:
            return
        self._gpu_polling = True

        def _worker():
            val = None
            try:
                # 1. Intentar NVIDIA (nvidia-smi)
                out = subprocess.check_output(
                    ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                    stderr=subprocess.DEVNULL,
                    timeout=0.8,
                ).decode("utf-8", errors="ignore").strip()
                if out:
                    first_line = out.splitlines()[0].strip()
                    if first_line.isdigit():
                        val = int(first_line)
            except Exception:
                pass

            if val is None:
                try:
                    # 2. Intentar AMD / Intel sysfs (gpu_busy_percent)
                    for path in glob.glob("/sys/class/drm/card*/device/gpu_busy_percent"):
                        with open(path, "r", encoding="utf-8") as fh:
                            txt = fh.read().strip()
                            if txt.isdigit():
                                val = max(val or 0, int(txt))
                except Exception:
                    pass

            if val is not None:
                self.gpu_pct = max(0, min(100, val))
            self._gpu_polling = False

        threading.Thread(target=_worker, daemon=True).start()

    def _read_rss_mb(self) -> int:
        try:
            with open("/proc/self/status", "r", encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("VmRSS:"):
                        kb = int(line.split()[1])
                        return max(1, kb // 1024)
        except Exception:
            pass
        return 64

    def _read_cpu_pct(self) -> int:
        try:
            with open("/proc/stat", "r", encoding="utf-8") as fh:
                first = fh.readline()
            parts = [int(x) for x in first.split()[1:]]
            idle = parts[3] + (parts[4] if len(parts) > 4 else 0)
            total = sum(parts)
            diff_total = total - self._prev_total
            diff_idle = idle - self._prev_idle
            self._prev_total = total
            self._prev_idle = idle
            if diff_total > 0:
                return max(1, min(99, int(round(100.0 * (diff_total - diff_idle) / diff_total))))
        except Exception:
            pass
        return 2

    def refresh_stats(self):
        self._poll_gpu_async()
        rss_mb = self._read_rss_mb() + self.bonus_atun_mb
        cpu_pct = self._read_cpu_pct()
        self.lbl_gpu.setText(
            f'<span style="color:#ff79c6;">GPU</span> <span style="color:#d5dcf9;">{self.gpu_pct}%</span>'
        )
        self.lbl_ram.setText(
            f'<span style="color:#9ece6a;">🐟</span> <span style="color:#d5dcf9;">{rss_mb}MB</span>'
        )
        self.lbl_cpu.setText(
            f'<span style="color:#7dcfff;">⚡</span> <span style="color:#d5dcf9;">{cpu_pct}%</span>'
        )


# ── Contenedor Principal Unificado (Única GUI de Cloe) ────────────────────────
class CloePet(QWidget):
    """
    Única GUI de Cloe:
    Combina el diseño de Cloe con fondo cristal,
    conversación de voz fluida (1 clic mantenido = push-to-talk, doble clic = charla continua)
    y burbuja/panel contextual siempre al costado izquierdo.
    """

    TOTAL_W = 380 + 14 + 168   # [Pop-up Lateral 380px] + [14px margen] + [Columna Mascota 168px]
    TOTAL_H = 515

    def __init__(self):
        super().__init__()
        self._drag_pos = None
        self._press_global_pos = None
        self._dragging = False
        self._hold_listening = False

        self._face = NEKO_KAOMOJIS["idle"][0]
        self._emote_icon = "🐾"
        self._face_idx = 0
        self._state_mode = "idle"
        self._pulse_phase = 0.0
        self._pulse_dir = 1
        self._mic_level = 0.0

        self.messages = []
        self.tools = []
        self.services = {}
        self._busy = False
        self._voice_io = None
        self._voice_loading = False
        self._voice_enabled = True
        self._pending_listen = False
        self._voice_loader = None
        self._listen_thread: VoiceListenThread | None = None
        self._worker: CloeWorker | None = None
        self._media_fetcher: ContextMediaFetcher | None = None
        self._cat_fetcher: RandomCatFetcher | None = None
        self._last_cat_time: float = 0.0
        self._cat_cooldown_extra_ms: int = 0

        # Estado de Recordatorios / Temporizador / Pomodoro activo (Módulo 1)
        self._timer_end_time: float = 0.0
        self._timer_total_s: float = 1.0
        self._timer_label: str = ""
        self._timer_kind: str = "reminder"

        self._conversation_mode = False
        self._sleeping = False
        self._streaming_buffer = ""
        self._history_log: list[tuple[str, str]] = []

        self._setup_host_window()
        self._build_side_by_side_layout()
        self._setup_voice_controls()
        self._connect_backend()

        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.timeout.connect(self._begin_hold_to_talk)

        self._revert_state_timer = QTimer(self)
        self._revert_state_timer.setSingleShot(True)
        self._revert_state_timer.timeout.connect(
            lambda: self._set_state_mode("sleeping" if self._sleeping else "idle")
        )

        self._idle_timer = QTimer(self)
        self._idle_timer.timeout.connect(self._next_face)
        self._idle_timer.start(3600)

        self._glow_timer = QTimer(self)
        self._glow_timer.timeout.connect(self._tick_glow)
        self._glow_timer.start(40)

        self._solo_timer = QTimer(self)
        self._solo_timer.setSingleShot(True)
        self._solo_timer.timeout.connect(self._hablar_sola)

        self._cat_timer = QTimer(self)
        self._cat_timer.setSingleShot(True)
        self._cat_timer.timeout.connect(self._trigger_random_cat)

        self._reminder_tick_timer = QTimer(self)
        self._reminder_tick_timer.timeout.connect(self._tick_reminder_countdown)

        self._topmost_timer = QTimer(self)
        self._topmost_timer.timeout.connect(self._keep_on_top_tick)
        self._topmost_timer.start(1500)

    def _setup_host_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysStackOnTop, True)
        self.setFixedSize(self.TOTAL_W, self.TOTAL_H)

    def showEvent(self, event):
        super().showEvent(event)
        self._enforce_always_on_top()

    def _keep_on_top_tick(self):
        if self.isVisible():
            self.raise_()

    def _enforce_always_on_top(self):
        """Aplica estado Always-On-Top (above + sticky) en el gestor de ventanas de Linux."""
        self.raise_()
        try:
            wid = int(self.winId())
        except Exception:
            return
        hex_wid = hex(wid)

        def _apply_x11():
            for cmd in (
                ["wmctrl", "-i", "-r", hex_wid, "-b", "add,above,sticky"],
                [
                    "xprop",
                    "-id",
                    str(wid),
                    "-f",
                    "_NET_WM_STATE",
                    "32a",
                    "-set",
                    "_NET_WM_STATE",
                    "_NET_WM_STATE_ABOVE,_NET_WM_STATE_STAYS_ON_TOP,_NET_WM_STATE_STICKY",
                ],
            ):
                try:
                    subprocess.run(
                        cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=1.5,
                        check=False,
                    )
                except Exception:
                    pass

        threading.Thread(target=_apply_x11, daemon=True).start()

    def _build_side_by_side_layout(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        # Columna izquierda (380 px): Burbuja Pop-up / Panel Contextual AL COSTADO
        self._left_slot = QWidget(self)
        self._left_slot.setFixedSize(380, self.TOTAL_H)
        self._left_slot.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        left_layout = QVBoxLayout(self._left_slot)
        left_layout.setContentsMargins(0, 0, 0, 6)
        left_layout.setSpacing(0)

        self._popup_panel = PopupSidePanel(self._left_slot)
        self._popup_panel.text_submitted.connect(self._on_panel_text_submitted)
        self._popup_panel.stop_requested.connect(self._stop_generation)
        self._popup_panel.clear_requested.connect(self._clear_chat)
        self._popup_panel.kaomoji_reaction_requested.connect(lambda: self.pet_action("love"))
        self._popup_panel.song_play_requested.connect(self._on_song_play_requested)
        self._popup_panel.visibility_changed.connect(self._update_mask)

        left_layout.addStretch(1)
        left_layout.addWidget(
            self._popup_panel,
            alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom,
        )

        # Columna derecha (168 px): Mascota NekoOrb + Indicador de Recursos + Dock de acciones debajo
        self._right_slot = QWidget(self)
        self._right_slot.setFixedSize(168, self.TOTAL_H)
        self._right_slot.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        right_col = QVBoxLayout(self._right_slot)
        right_col.setContentsMargins(0, 0, 0, 6)
        right_col.setSpacing(4)
        right_col.addStretch(1)

        self._orb = NekoOrbWidget(self)
        right_col.addWidget(self._orb, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._stats_bar = PetStatsBar(self)
        right_col.addWidget(self._stats_bar, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._dock = PetDockWidget(self)
        right_col.addWidget(self._dock, alignment=Qt.AlignmentFlag.AlignHCenter)

        root.addWidget(self._left_slot)
        root.addWidget(self._right_slot)

        QTimer.singleShot(0, self._update_mask)

    def _update_mask(self):
        """Aplica máscara transparente para que solo la mascota, recursos, dock y el pop-up visible reciban clics."""
        if self._left_slot.layout() is not None:
            self._left_slot.layout().activate()
        if self._right_slot.layout() is not None:
            self._right_slot.layout().activate()
        if self.layout() is not None:
            self.layout().activate()

        orb_pos = self._orb.mapTo(self, QPoint(0, 0))
        orb_rect = QRectF(orb_pos.x(), orb_pos.y(), self._orb.width(), self._orb.height()).toRect()
        region = QRegion(orb_rect)

        stats_pos = self._stats_bar.mapTo(self, QPoint(0, 0))
        stats_rect = QRectF(stats_pos.x(), stats_pos.y(), self._stats_bar.width(), self._stats_bar.height()).toRect()
        region = region.united(QRegion(stats_rect))

        dock_pos = self._dock.mapTo(self, QPoint(0, 0))
        dock_rect = QRectF(dock_pos.x(), dock_pos.y(), self._dock.width(), self._dock.height()).toRect()
        region = region.united(QRegion(dock_rect))

        if self._popup_panel.isVisible():
            pp_pos = self._popup_panel.mapTo(self, QPoint(0, 0))
            pp_rect = (
                QRectF(
                    pp_pos.x(),
                    pp_pos.y(),
                    self._popup_panel.width(),
                    self._popup_panel.height(),
                )
                .toRect()
                .adjusted(-2, -2, 2, 2)
            )
            region = region.united(QRegion(pp_rect))

        self.setMask(region)
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_mask()

    # ── Arrastre de la Burbuja y de Cloe por toda la pantalla (Wayland + X11) ──
    def _perform_window_move(self, global_pos: QPoint):
        wh = self.windowHandle()
        if wh is not None and QApplication.platformName().lower().startswith("wayland"):
            wh.startSystemMove()
            self._drag_pos = None
            return
        if self._drag_pos is not None:
            self.move(global_pos - self._drag_pos)

    def begin_panel_drag(self, global_pos: QPoint):
        self._press_global_pos = global_pos
        self._drag_pos = global_pos - self.frameGeometry().topLeft()
        self._dragging = False

    def update_panel_drag(self, global_pos: QPoint):
        if self._drag_pos is None:
            return
        if self._press_global_pos and (global_pos - self._press_global_pos).manhattanLength() > 5:
            self._dragging = True
            self._perform_window_move(global_pos)

    def end_panel_drag(self):
        self._dragging = False
        self._drag_pos = None

    # ── Parada de Actividad Autónoma (para Modo Dormir / No Molestar 🌙) ──────
    def _stop_all_autonomous_activity(self):
        """Detiene inmediatamente cualquier charla espontánea, gatos aleatorios, voz o generación en curso."""
        self._conversation_mode = False
        self._pending_listen = False
        self._hold_listening = False
        self._solo_timer.stop()
        self._cat_timer.stop()
        self._revert_state_timer.stop()
        if self._listen_thread is not None and self._listen_thread.isRunning():
            self._listen_thread.cancel()
        if self._worker is not None and self._worker.isRunning():
            self._worker.abort()
        if self._voice_io is not None:
            self._voice_io.stop_speaking()
        self._busy = False
        self._popup_panel.set_generating(False)

    # ── Acciones Felinas del Dock y Reacciones ────────────────────────────────
    def pet_action(self, action: str):
        if action == "love":
            self._stats_bar.purr_pct = min(100, self._stats_bar.purr_pct + 5)
            self._stats_bar.refresh_stats()
            self._orb.spawn_particles("♥", 4)
            self._orb.spawn_particles("nya~", 2)
            if not self._sleeping:
                self._set_state_mode("happy", custom_icon="💖", duration_ms=2400)
        elif action == "feed":
            self._stats_bar.bonus_atun_mb += 16
            self._stats_bar.refresh_stats()
            self._orb.spawn_particles("+ATÚN", 3)
            if not self._sleeping:
                self._set_state_mode("happy", custom_icon="🐟", custom_face="(=^･◡･^=)🐟", duration_ms=2400)
        elif action == "pomodoro":
            if self._timer_end_time > time.monotonic():
                self._cancel_reminder_timer()
                if not self._sleeping:
                    self._set_state_mode("idle", custom_icon="🐾")
            else:
                self._start_reminder_timer(
                    25 * 60,
                    "Sesión Pomodoro de concentración (25 min)",
                    kind="pomodoro",
                )
                if not self._sleeping:
                    self._set_state_mode("happy", custom_icon="🍅", custom_face="(=^･ω･^=)🍅", duration_ms=2200)
        elif action == "laser":
            self._orb.spawn_particles("!", 3)
            self._sleeping = False
            self._dock.set_sleep_active(False)
            self._set_state_mode("laser", custom_icon="🔴", custom_face="／(=✪ x ✪=)＼", duration_ms=3400)
        elif action == "sleep":
            if self._sleeping or self._state_mode == "sleeping":
                self._sleeping = False
                self._dock.set_sleep_active(False)
                self._set_state_mode("idle", custom_icon="🐾")
                self._schedule_solo()
                self._schedule_random_cat()
            else:
                self._sleeping = True
                self._dock.set_sleep_active(True)
                self._stop_all_autonomous_activity()
                self._orb.spawn_particles("zZz", 3)
                self._set_state_mode("sleeping", custom_icon="💤", custom_face="( -ω-) zZz")

    def toggle_bubble(self):
        self._popup_panel.set_bubble_visible(not self._popup_panel.isVisible())

    def toggle_voice_button(self):
        self._toggle_voz(not self._voice_enabled)
        self._dock.btn_voice.setText("🔊" if self._voice_enabled else "🔇")

    # ── Interacción con el Círculo (1 Clic Mantenido vs Doble Clic) ───────────
    def orb_mouse_press(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_global_pos = event.globalPosition().toPoint()
            self._drag_pos = self._press_global_pos - self.frameGeometry().topLeft()
            self._dragging = False
            if not self._sleeping:
                self._hold_timer.start(140)

    def orb_mouse_move(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self._drag_pos is not None:
            curr = event.globalPosition().toPoint()
            if self._press_global_pos and (curr - self._press_global_pos).manhattanLength() > 8:
                self._dragging = True
                self._hold_timer.stop()
                if self._hold_listening:
                    self._pending_listen = False
                    self._cancel_listening()
                    self._hold_listening = False
                self._perform_window_move(curr)

    def orb_mouse_release(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._hold_timer.stop()
        was_dragging = self._dragging
        self._dragging = False
        self._drag_pos = None

        if was_dragging:
            return

        # Si está durmiendo (🌙), no hacer nada al hacer clic corto en el círculo (solo se despierta con 🌙)
        if self._sleeping:
            return

        # Si estaba manteniendo presionado para hablar: al soltar deja de escuchar y envía
        if self._hold_listening:
            self._hold_listening = False
            self._pending_listen = False
            if self._listen_thread is not None and self._listen_thread.isRunning():
                self._listen_thread.finish_recording()
            else:
                self._set_state_mode("idle")
            return

        # Si fue un clic corto (< 140 ms):
        if self._conversation_mode:
            self._set_conversation_mode(False)
            return
        if self._listen_thread is not None and self._listen_thread.isRunning():
            self._listen_thread.finish_recording()
            return
        if self._state_mode == "speaking" and self._voice_io is not None:
            self._stop_generation()
            return

        # Clic corto en reposo: acariciar a Cloe y mostrar burbuja si estaba oculta
        self.pet_action("love")
        if not self._popup_panel.isVisible():
            self._popup_panel.set_bubble_visible(True)

    def orb_mouse_double_click(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._hold_timer.stop()
            self._pending_listen = False
            if self._sleeping:
                return
            if self._hold_listening:
                self._cancel_listening()
                self._hold_listening = False
            self._set_conversation_mode(not self._conversation_mode)

    def _begin_hold_to_talk(self):
        """Se activa al mantener presionado el círculo: escucha mientras mantienes presionado."""
        if self._dragging or self._conversation_mode or self._sleeping:
            return
        if self._voice_io is not None:
            self._voice_io.stop_speaking()
        if self._worker is not None and self._worker.isRunning():
            self._worker.abort()
        self._hold_listening = True
        if self._voice_io is None:
            self._pending_listen = True
            self._init_voice_async(then_listen=True)
        else:
            self._start_listening()

    def _set_conversation_mode(self, enabled: bool):
        self._conversation_mode = enabled
        if enabled:
            self._voice_enabled = True
            self._dock.btn_voice.setText("🔊")
            # En charla continua no es necesario abrir el cuadro de diálogo
            if self._popup_panel.isVisible():
                self._popup_panel.set_bubble_visible(False)
            if self._voice_io is not None:
                self._start_listening()
            else:
                self._init_voice_async(then_listen=True)
        else:
            self._cancel_listening()
            if self._voice_io is not None:
                self._voice_io.stop_speaking()
            self._set_state_mode("sleeping" if self._sleeping else "idle")

    # ── Menú Contextual (Clic Derecho) ────────────────────────────────────────
    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: rgba(18, 21, 33, 240);
                color: #d5dcf9;
                border: 1px solid #4d5885;
                border-radius: 11px;
                padding: 4px;
            }
            QMenu::item:selected {
                background-color: rgba(125, 207, 255, 55);
                color: #ffffff;
                border-radius: 7px;
            }
            QMenu::item { padding: 6px 14px; font-size: 12px; }
        """)
        panel_act = QAction("💬  Mostrar / Ocultar burbuja lateral", self)
        panel_act.triggered.connect(self.toggle_bubble)

        sleep_act = QAction("🌙  Modo Dormir / No Molestar", self)
        sleep_act.setCheckable(True)
        sleep_act.setChecked(self._sleeping)
        sleep_act.triggered.connect(lambda: self.pet_action("sleep"))

        conv_act = QAction("🎙️  Charla continua (doble clic)", self)
        conv_act.setCheckable(True)
        conv_act.setChecked(self._conversation_mode)
        conv_act.toggled.connect(self._set_conversation_mode)

        voz_act = QAction("🔊  Voz de Cloe activa", self)
        voz_act.setCheckable(True)
        voz_act.setChecked(self._voice_enabled)
        voz_act.toggled.connect(self._toggle_voz)

        salir = QAction("✕  Salir", self)
        salir.triggered.connect(self._shutdown)

        menu.addAction(panel_act)
        menu.addAction(sleep_act)
        menu.addSeparator()
        menu.addAction(conv_act)
        menu.addAction(voz_act)
        menu.addSeparator()
        menu.addAction(salir)
        menu.exec(event.globalPos())

    # ── Configuración de Controles de IA y Voz ────────────────────────────────
    def _setup_voice_controls(self):
        # 1. Selector de Proveedor IA (Auto / Groq / Gemini / Ollama)
        llm_combo = self._popup_panel.llm_combo
        curr_prov = os.getenv("CLOE_LLM_PROVIDER", "auto").strip().lower()
        idx = llm_combo.findData(curr_prov)
        if idx >= 0:
            llm_combo.setCurrentIndex(idx)
        self._refresh_api_key_placeholder()
        llm_combo.currentIndexChanged.connect(self._on_llm_provider_changed)
        self._popup_panel.btn_save_key.clicked.connect(self._on_save_api_key)
        self._popup_panel.api_key_field.returnPressed.connect(self._on_save_api_key)

        # 2. Controles de Voz TTS
        eng_combo = self._popup_panel.engine_combo
        default_eng = os.getenv("CLOE_TTS_ENGINE", "edge").strip().lower()
        if default_eng in ("edge", "kokoro", "piper", "espeak", "none"):
            eng_combo.setCurrentText(default_eng)
        self._populate_voices(eng_combo.currentText())

        eng_combo.currentTextChanged.connect(self._on_engine_changed)
        self._popup_panel.voice_combo.currentIndexChanged.connect(self._apply_voice_settings)
        self._popup_panel.speed_slider.valueChanged.connect(self._on_speed_changed)

    def _refresh_api_key_placeholder(self):
        prov = self._popup_panel.llm_combo.currentData() or "auto"
        has_groq = bool(os.getenv("GROQ_API_KEY", "").strip())
        has_gem = bool(os.getenv("GEMINI_API_KEY", "").strip())
        if prov == "gemini":
            status = "✓ GEMINI_API_KEY activa" if has_gem else "Pega tu GEMINI_API_KEY (AIza...)"
        elif prov == "groq":
            status = "✓ GROQ_API_KEY activa" if has_groq else "Pega tu GROQ_API_KEY (gsk_...)"
        else:
            if has_groq:
                status = "✓ Groq Cloud activo (0% GPU)"
            elif has_gem:
                status = "✓ Gemini Cloud activo (0% GPU)"
            else:
                status = "Pega Key de Groq (gsk_...) o Gemini (AIza...)"
        self._popup_panel.api_key_field.setPlaceholderText(status)

    def _on_llm_provider_changed(self):
        prov = self._popup_panel.llm_combo.currentData() or "auto"
        save_env_var("CLOE_LLM_PROVIDER", prov)
        self._refresh_api_key_placeholder()
        active_prov, _ = get_active_llm_info()
        if active_prov in ("groq", "gemini"):
            threading.Thread(
                target=unload_ollama_vram,
                args=(getattr(self, "client", None),),
                daemon=True,
            ).start()

    def _on_save_api_key(self):
        key_txt = self._popup_panel.api_key_field.text().strip()
        if not key_txt:
            return
        sel_prov = self._popup_panel.llm_combo.currentData() or "auto"
        if key_txt.startswith("gsk_") or sel_prov == "groq":
            save_env_var("GROQ_API_KEY", key_txt)
            if sel_prov == "ollama":
                save_env_var("CLOE_LLM_PROVIDER", "groq")
                idx = self._popup_panel.llm_combo.findData("groq")
                if idx >= 0:
                    self._popup_panel.llm_combo.setCurrentIndex(idx)
        else:
            save_env_var("GEMINI_API_KEY", key_txt)
            if sel_prov == "ollama":
                save_env_var("CLOE_LLM_PROVIDER", "gemini")
                idx = self._popup_panel.llm_combo.findData("gemini")
                if idx >= 0:
                    self._popup_panel.llm_combo.setCurrentIndex(idx)

        self._popup_panel.api_key_field.clear()
        self._refresh_api_key_placeholder()
        threading.Thread(
            target=unload_ollama_vram,
            args=(getattr(self, "client", None),),
            daemon=True,
        ).start()
        self.pet_action("love")

    def _populate_voices(self, engine: str):
        vc = self._popup_panel.voice_combo
        vc.blockSignals(True)
        vc.clear()
        for label, val in VOICE_PRESETS.get(engine, []):
            vc.addItem(label, val)
        if vc.count() == 0:
            vc.addItem("Predeterminada", "")
        vc.blockSignals(False)

    def _on_engine_changed(self, engine: str):
        self._populate_voices(engine)
        self._apply_voice_settings()

    def _on_speed_changed(self, value: int):
        speed = value / 100.0
        self._popup_panel.speed_label.setText(f"Ritmo: {speed:.2f}x")
        if self._voice_io is not None:
            self._voice_io.reconfigure_tts(speed=speed)

    def _apply_voice_settings(self):
        if self._voice_io is None:
            return
        engine = self._popup_panel.engine_combo.currentText()
        voice_id = self._popup_panel.voice_combo.currentData() or ""
        speed = self._popup_panel.speed_slider.value() / 100.0
        self._voice_io.reconfigure_tts(engine=engine, voice=voice_id, speed=speed)

    # ── Estados y Kaomojis ────────────────────────────────────────────────────
    def _set_state_mode(
        self,
        mode: str,
        custom_icon: str | None = None,
        custom_face: str | None = None,
        duration_ms: int = 0,
    ):
        self._revert_state_timer.stop()
        self._state_mode = mode
        icons = {
            "idle": "🐾",
            "listening": "🎙️",
            "thinking": "💭",
            "speaking": "🔊",
            "happy": "💖",
            "laser": "🔴",
            "sleeping": "💤",
        }
        self._emote_icon = custom_icon or icons.get(mode, "🐾")
        faces = NEKO_KAOMOJIS.get(mode, NEKO_KAOMOJIS["idle"])
        self._face = custom_face or random.choice(faces)
        if mode == "idle":
            self._mic_level = 0.0
        self._popup_panel.set_state_badge(mode)
        self._orb.update()
        if duration_ms > 0:
            self._revert_state_timer.start(duration_ms)

    def _next_face(self):
        if self._state_mode == "idle":
            idle_list = NEKO_KAOMOJIS["idle"]
            self._face_idx = (self._face_idx + 1) % len(idle_list)
            self._face = idle_list[self._face_idx]
        elif self._state_mode in ("speaking", "listening", "thinking"):
            self._face = random.choice(NEKO_KAOMOJIS.get(self._state_mode, NEKO_KAOMOJIS["idle"]))
        self._orb.update()

    def _tick_glow(self):
        step = 0.065 if self._state_mode in ("listening", "speaking") else 0.025
        self._pulse_phase += step * self._pulse_dir
        if self._pulse_phase >= 1.0:
            self._pulse_phase = 1.0
            self._pulse_dir = -1
        elif self._pulse_phase <= 0.0:
            self._pulse_phase = 0.0
            self._pulse_dir = 1
        self._orb.update()

    # ── Pipeline de Voz ───────────────────────────────────────────────────────
    def _init_voice_async(self, then_listen=False):
        if self._voice_io is not None:
            if then_listen:
                self._start_listening()
            return
        if self._voice_loading:
            self._pending_listen = self._pending_listen or then_listen
            return
        self._voice_loading = True
        self._voice_loader = VoiceLoader()
        self._voice_loader.ready.connect(lambda v: self._on_voice_ready(v, then_listen))
        self._voice_loader.failed.connect(self._on_voice_failed)
        self._voice_loader.start()

    def _on_voice_ready(self, voice, then_listen=False):
        self._voice_loading = False
        self._voice_io = voice
        loaded_engine = getattr(voice.tts, "name", "kokoro")
        if loaded_engine in ("edge", "kokoro", "piper", "espeak", "none"):
            self._popup_panel.engine_combo.blockSignals(True)
            self._popup_panel.engine_combo.setCurrentText(loaded_engine)
            self._populate_voices(loaded_engine)
            self._popup_panel.engine_combo.blockSignals(False)
        if then_listen or self._pending_listen:
            self._pending_listen = False
            self._start_listening()

    def _on_voice_failed(self, _message: str):
        self._voice_loading = False

    def _start_listening(self):
        if self._voice_io is None or self._busy:
            return
        if self._listen_thread is not None and self._listen_thread.isRunning():
            return
        self._set_state_mode("listening")
        self._listen_thread = VoiceListenThread(self._voice_io)
        self._listen_thread.level_changed.connect(self._on_mic_level)
        self._listen_thread.transcribed.connect(self._on_transcribed)
        self._listen_thread.failed.connect(self._on_listen_failed)
        self._listen_thread.start()

    def _cancel_listening(self):
        if self._listen_thread is not None and self._listen_thread.isRunning():
            self._listen_thread.cancel()
        self._set_state_mode("idle")

    def _on_mic_level(self, level: float, _state: str):
        self._mic_level = level
        self._orb.update()

    def _on_transcribed(self, text: str):
        self._mic_level = 0.0
        cleaned = (text or "").strip()
        if not cleaned:
            self._set_state_mode("idle")
            if self._conversation_mode:
                QTimer.singleShot(180, self._start_listening)
            return
        self._append_message("Tú", cleaned)
        self._send(cleaned, from_voice=True)

    def _on_listen_failed(self, _message: str):
        self._mic_level = 0.0
        self._set_state_mode("idle")
        if self._conversation_mode:
            QTimer.singleShot(1000, self._start_listening)

    def _toggle_voz(self, checked: bool):
        self._voice_enabled = checked
        self._dock.btn_voice.setText("🔊" if checked else "🔇")
        if not checked and self._voice_io is not None:
            self._voice_io.stop_speaking()

    # ── Conexión con Ollama y Servicios ───────────────────────────────────────
    def _connect_backend(self):
        class Loader(QThread):
            done = pyqtSignal(dict, list, list)

            def run(self_inner):
                services = connect_services()
                client = ollama.Client(host=OLLAMA_HOST)
                tools = available_tool_names(services)
                modelfile = get_modelfile_system(client)
                hints = build_tool_hints(services, conversational_voice=True)
                system = (modelfile + "\n\n" + hints).strip() if hints else modelfile
                msgs = [{"role": "system", "content": system}] if system else []
                self_inner.done.emit(services, tools, msgs)

        self._loader = Loader()
        self._loader.done.connect(self._on_backend_ready)
        self._loader.start()

    def _on_backend_ready(self, services, tools, messages):
        self.services = services
        self.tools = tools
        self.messages = messages
        self.client = ollama.Client(host=OLLAMA_HOST)
        self.dispatcher = ToolDispatcher(services)
        if services.get("calls") is not None:
            atexit.register(services["calls"].close)
        self._schedule_solo()
        self._schedule_random_cat(first_run=True)
        self._init_voice_async()

    # ── Historial, Streaming y Tarjetas de Contexto ───────────────────────────
    def _render_history_view(self, streaming_text: str | None = None):
        blocks: list[str] = []
        for role, msg in self._history_log:
            blocks.append(self._format_history_item(role, msg))
        if streaming_text is not None:
            blocks.append(self._format_history_item("Cloe", streaming_text + " ▋"))
        self._popup_panel._history_view.setHtml("".join(blocks))
        sb = self._popup_panel._history_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _format_history_item(self, role: str, text: str) -> str:
        is_user = role == "Tú"
        header = "HUMANO" if is_user else "CLOE (=^･ω･^=)"
        h_col = "#bb9af7" if is_user else "#7dcfff"
        bg = "rgba(26, 30, 46, 170)" if is_user else "rgba(18, 21, 33, 195)"
        margin = "margin: 5px 0px 5px 18px;" if is_user else "margin: 5px 12px 5px 0px;"
        body = format_markdown_html(text)
        return (
            f'<div style="{margin} padding: 7px 10px; background-color: {bg}; '
            'border: 1px solid #2a304a; border-radius: 10px;">'
            f'<div style="color: {h_col}; font-family: monospace; font-size: 9.5px; font-weight: 700; margin-bottom: 2px;">{header}</div>'
            f'<div style="color: #d5dcf9; font-size: 12px;">{body}</div>'
            "</div>"
        )

    def _append_message(self, role: str, text: str):
        self._history_log.append((role, text))
        if len(self._history_log) > 60:
            self._history_log = self._history_log[-60:]
        self._render_history_view()

    def _clear_chat(self):
        self._stop_generation()
        self._history_log.clear()
        self.messages = [m for m in self.messages if m.get("role") == "system"]
        self._popup_panel._history_view.clear()
        self._popup_panel._user_pill.hide()
        self._popup_panel._metrics_lbl.hide()
        self._popup_panel.set_cards([])
        self._popup_panel.update_single_exchange(
            None,
            "**ฅ^•ﻌ•^ฅ ¡Nyaa~!** Arenero de memoria limpio y caché fresca. ¿Qué hacemos ahora? `(=^･ω･^=)`",
        )
        self.pet_action("love")

    def _stop_generation(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.abort()
        if self._voice_io is not None:
            self._voice_io.stop_speaking()
        self._busy = False
        self._popup_panel.set_generating(False)
        self._set_state_mode("idle")

    def _on_panel_text_submitted(self, text: str):
        self._cancel_listening()
        if self._voice_io is not None:
            self._voice_io.stop_speaking()
        self._append_message("Tú", text)
        self._send(text, from_voice=False)

    def _on_song_play_requested(self, query: str, fallback_url: str):
        if self.services.get("spotify") and query:
            play_track(self.services["spotify"], query)
        elif fallback_url:
            QDesktopServices.openUrl(QUrl(fallback_url))

    # ── Recordatorios, Temporizadores y Pomodoro (Módulo 1) ───────────────────
    def _start_reminder_timer(self, seconds: int, label: str, kind: str = "reminder"):
        self._timer_total_s = float(max(1, seconds))
        self._timer_end_time = time.monotonic() + self._timer_total_s
        self._timer_label = label
        self._timer_kind = kind
        if not self._reminder_tick_timer.isActive():
            self._reminder_tick_timer.start(500)
        self._dock.set_pomodoro_active(True)
        self._orb.spawn_particles("🍅" if kind == "pomodoro" else "⏳", 3)
        self._orb.update()

    def _cancel_reminder_timer(self):
        self._timer_end_time = 0.0
        self._timer_label = ""
        self._reminder_tick_timer.stop()
        self._dock.set_pomodoro_active(False)
        self._orb.update()

    def _tick_reminder_countdown(self):
        if self._timer_end_time <= 0.0:
            self._reminder_tick_timer.stop()
            self._dock.set_pomodoro_active(False)
            return
        rem = self._timer_end_time - time.monotonic()
        if rem > 0.0:
            self._orb.update()
            return

        # ¡Tiempo cumplido!
        self._timer_end_time = 0.0
        self._reminder_tick_timer.stop()
        self._dock.set_pomodoro_active(False)
        label = self._timer_label or "¡Tiempo cumplido!"
        kind = self._timer_kind
        self._orb.update()

        if self._state_mode == "sleeping":
            self._set_state_mode("idle")

        if not self._popup_panel.isVisible():
            self._popup_panel.set_bubble_visible(True)

        icon = "🍅" if kind == "pomodoro" else "⏰"
        title = "¡Pomodoro completado!" if kind == "pomodoro" else "¡Recordatorio Michi!"
        alert_md = f"**{icon} {title} (=^･∇･^=)ﾉ**\n👉 **{label}**"
        self._popup_panel._user_pill.hide()
        self._popup_panel.update_single_exchange(
            None,
            alert_md,
            streaming=False,
            metrics=f"{icon} temporizador finalizado",
        )
        self._append_message("Cloe", alert_md)
        self._orb.spawn_particles(icon, 4)
        self._orb.spawn_particles("nya~", 3)
        self._set_state_mode("happy", custom_icon=icon, duration_ms=3800)

        if self._voice_io is not None and self._voice_enabled and not self._busy:
            spoken = (
                f"¡Oye! Se cumplió tu Pomodoro: {label}"
                if kind == "pomodoro"
                else f"¡Oye! Te recuerdo: {label}"
            )
            threading.Thread(
                target=lambda: self._voice_io.speak(spoken),
                daemon=True,
            ).start()

    def _send(self, text: str, from_voice: bool = False):
        if not hasattr(self, "client"):
            QTimer.singleShot(400, lambda t=text, fv=from_voice: self._send(t, fv))
            return
        if self._busy:
            return
        self._busy = True
        self._last_user_input = text
        self._streaming_buffer = ""
        self._set_state_mode("thinking")
        self._popup_panel.set_generating(True)
        self._popup_panel.set_cards([])

        # Detectar si el usuario pidió un recordatorio, temporizador o Pomodoro
        llm_input = text
        rem_req = parse_reminder_request(text)
        if rem_req is not None:
            if rem_req.get("action") == "start":
                secs = int(rem_req["seconds"])
                lbl = str(rem_req["label"])
                kind = str(rem_req.get("kind", "reminder"))
                self._start_reminder_timer(secs, lbl, kind)
                mins, rem_s = divmod(secs, 60)
                human_t = f"{mins} min" + (f" {rem_s} seg" if rem_s else "") if mins else f"{secs} seg"
                llm_input = (
                    f"{text}\n"
                    f"[Sistema: Ya activaste en pantalla el temporizador ({human_t}) para '{lbl}'. "
                    "Confírmale al usuario con entusiasmo en 1 sola oración corta que le avisarás cuando termine.]"
                )
            elif rem_req.get("action") == "cancel":
                self._cancel_reminder_timer()
                llm_input = (
                    f"{text}\n"
                    "[Sistema: Ya cancelaste el temporizador activo en pantalla. Confírmalo en 1 oración corta.]"
                )

        # Detectar si el usuario pidió que Cloe mire su pantalla (Módulo 2)
        screen_b64: str | None = None
        self._pending_screen_card: dict | None = None
        self._used_vision = False
        if is_screen_vision_request(text):
            # Hacer transparente un instante la burbuja de Cloe para capturar el escritorio limpio detrás
            self.setWindowOpacity(0.0)
            QApplication.processEvents()
            try:
                jpeg_bytes, b64_str = capture_screen_jpeg()
                win_ctx = get_active_window_context()
            finally:
                self.setWindowOpacity(1.0)
                QApplication.processEvents()

            if jpeg_bytes and b64_str:
                screen_b64 = b64_str
                self._used_vision = True
                self._pending_screen_card = {
                    "kind": "cat_photo",
                    "title": "👁️ Pantalla capturada",
                    "subtitle": win_ctx or "Captura analizada por Cloe",
                    "image_bytes": jpeg_bytes,
                    "url": "",
                }
                self._popup_panel.set_cards([self._pending_screen_card])
                self._orb.spawn_particles("👁️", 3)
                if win_ctx:
                    llm_input = f"{llm_input}\n[{win_ctx}]"
            else:
                self._busy = False
                self._popup_panel.set_generating(False)
                self._set_state_mode("idle")
                msg_err = (
                    "(=^･ω･^=)? No pude capturar tu pantalla directamente desde esta sesión. "
                    "Reinicia a Cloe para activar el modo X11/XWayland o copia el texto con `Ctrl+C` y pulsa **📋 Copiado**."
                )
                if not self._popup_panel.isVisible():
                    self._popup_panel.set_bubble_visible(True)
                self._popup_panel.update_single_exchange(text, msg_err, streaming=False)
                self._append_message("Cloe", msg_err)
                return

        # Solo abrir el cuadro de diálogo si NO estamos en charla continua ni hablando por voz
        if not self._conversation_mode and not from_voice and not self._popup_panel.isVisible():
            self._popup_panel.set_bubble_visible(True)

        self._popup_panel.update_single_exchange(text, "…", streaming=True)

        self._worker = CloeWorker(
            self.client,
            self.messages,
            self.tools,
            self.dispatcher,
            llm_input,
            voice_io=self._voice_io,
            speak_enabled=self._voice_enabled,
            conversational=from_voice or self._conversation_mode,
            image_b64=screen_b64,
        )
        self._worker.token_received.connect(self._on_stream_token)
        self._worker.response_ready.connect(self._on_response_text_done)
        self._worker.speech_finished.connect(self._on_turn_completed)
        self._worker.start()

    def _on_stream_token(self, token: str):
        if self._state_mode != "speaking":
            self._set_state_mode("speaking")
        self._streaming_buffer += token
        # Si la respuesta incluye un bloque de código, abrir la burbuja lateral para ver el código mientras Cloe explica
        if "```" in self._streaming_buffer and not self._popup_panel.isVisible():
            self._popup_panel.set_bubble_visible(True)
        if self._popup_panel.isVisible():
            self._popup_panel.update_single_exchange(
                getattr(self, "_last_user_input", None),
                self._streaming_buffer,
                streaming=True,
            )
            if self._popup_panel._history_mode:
                self._render_history_view(streaming_text=self._streaming_buffer)

    def _on_response_text_done(self, reply: str, tok_per_sec: float, token_count: int):
        self._streaming_buffer = ""
        self._append_message("Cloe", reply)

        last_input = getattr(self, "_last_user_input", "")
        prov, model_name = get_active_llm_info()
        if getattr(self, "_used_vision", False) and prov == "groq":
            model_name = "qwen3.8-27b-vision"
        metrics_str = (
            f"🐾 {tok_per_sec:.1f} tok/s ({token_count} tok)  ·  {prov}/{model_name}"
            if token_count > 0
            else None
        )
        self._popup_panel.update_single_exchange(
            last_input if last_input else None,
            reply,
            streaming=False,
            metrics=metrics_str,
        )

        term_card = pop_last_terminal_card()
        if term_card is not None:
            self._pending_terminal_card = term_card
            self._popup_panel.set_cards([term_card])
            if term_card.get("kind") == "terminal_confirm" and not self._popup_panel.isVisible():
                self._popup_panel.set_bubble_visible(True)
        else:
            self._pending_terminal_card = None

        self._media_fetcher = ContextMediaFetcher(last_input, reply)
        self._media_fetcher.cards_ready.connect(self._on_context_cards_ready)
        self._media_fetcher.start()

    def _on_context_cards_ready(self, cards: list):
        pending_sc = getattr(self, "_pending_screen_card", None)
        pending_tc = getattr(self, "_pending_terminal_card", None)
        if pending_sc is not None:
            cards = [pending_sc]
            self._pending_screen_card = None
        elif pending_tc is not None:
            cards = [pending_tc]
            self._pending_terminal_card = None
        self._popup_panel.set_cards(cards)
        if cards and not self._conversation_mode and not self._popup_panel.isVisible():
            self._popup_panel.set_bubble_visible(True)
        QTimer.singleShot(10, self._update_mask)

    def _on_turn_completed(self):
        self._busy = False
        self._popup_panel.set_generating(False)
        self._orb.spawn_particles("nya~", 2)
        self._set_state_mode("happy", custom_icon="✨", duration_ms=1800)
        if self._conversation_mode:
            QTimer.singleShot(140, self._start_listening)

    # ── Charla espontánea en Pop-up ───────────────────────────────────────────
    def _schedule_solo(self):
        if not hasattr(self, "client") or self._sleeping or self._state_mode == "sleeping":
            return
        delay = random.randint(120000, 210000)
        self._solo_timer.start(delay)

    def _hablar_sola(self):
        if self._sleeping or self._state_mode == "sleeping":
            return
        if (
            self._busy
            or self._state_mode != "idle"
            or self._conversation_mode
            or (self._listen_thread is not None and self._listen_thread.isRunning())
            or not hasattr(self, "client")
        ):
            self._schedule_solo()
            return
        prompt = random.choice(SOLO_PROMPTS)
        self._busy = True
        self._last_user_input = ""
        if not self._popup_panel.isVisible():
            self._popup_panel.set_bubble_visible(True)
        speak_solo = bool(self._voice_io and self._voice_io.config.speak_solo and self._voice_enabled)
        self._worker = CloeWorker(
            self.client,
            self.messages,
            self.tools,
            self.dispatcher,
            prompt,
            voice_io=self._voice_io,
            speak_enabled=speak_solo,
            conversational=True,
        )
        self._worker.token_received.connect(self._on_stream_token)
        self._worker.response_ready.connect(self._on_response_text_done)
        self._worker.speech_finished.connect(self._on_solo_completed)
        self._worker.start()

    def _on_solo_completed(self):
        self._busy = False
        self._popup_panel.set_generating(False)
        if not self._sleeping and self._state_mode != "sleeping":
            self._set_state_mode("idle", custom_icon="🐾")
            self._schedule_solo()

    # ── Gatos Aleatorios ("¡Mira esto!") con Cooldown Anti-Spam ───────────────
    def _schedule_random_cat(self, first_run: bool = False):
        if self._sleeping or self._state_mode == "sleeping":
            return
        # Tiempo base aleatorio + cooldown acumulado si salieron dos muy seguidos
        base_ms = random.randint(45000, 95000) if first_run else random.randint(60000, 175000)
        delay = base_ms + self._cat_cooldown_extra_ms
        self._cat_timer.start(delay)

    def _trigger_random_cat(self):
        if self._sleeping or self._state_mode == "sleeping":
            return
        if (
            self._busy
            or self._state_mode != "idle"
            or self._conversation_mode
            or (self._listen_thread is not None and self._listen_thread.isRunning())
            or (self._cat_fetcher is not None and self._cat_fetcher.isRunning())
        ):
            self._schedule_random_cat()
            return

        now = time.monotonic()
        if self._last_cat_time > 0:
            elapsed_s = now - self._last_cat_time
            # Si salió 1 y en un periodo corto (< 150s) intenta tirar otra, sumar cooldown extra
            if elapsed_s < 150.0:
                self._cat_cooldown_extra_ms = min(600000, self._cat_cooldown_extra_ms + 180000)
                if elapsed_s < 95.0:
                    # Demasiado pronto: posponer aplicando el nuevo cooldown acumulado
                    self._schedule_random_cat()
                    return
            elif elapsed_s > 300.0:
                # Si ya pasó bastante tiempo sin spam, reducir gradualmente la penalización
                self._cat_cooldown_extra_ms = max(0, self._cat_cooldown_extra_ms - 120000)

        self._cat_fetcher = RandomCatFetcher()
        self._cat_fetcher.cat_ready.connect(self._on_random_cat_ready)
        self._cat_fetcher.start()

    def _on_random_cat_ready(self, card: dict):
        if self._sleeping or self._state_mode == "sleeping" or self._busy or self._conversation_mode:
            return

        now = time.monotonic()
        if self._last_cat_time > 0 and (now - self._last_cat_time) < 160.0:
            # Si salieron dos en un periodo corto, sumar cooldown (+3 min extra) para las siguientes
            self._cat_cooldown_extra_ms = min(600000, self._cat_cooldown_extra_ms + 180000)
        self._last_cat_time = now

        if not self._popup_panel.isVisible():
            self._popup_panel.set_bubble_visible(True)

        msg = card.get("subtitle", "¡Mira esto! Mira qué michi me encontré ฅ^•ﻌ•^ฅ")
        self._popup_panel._user_pill.hide()
        self._popup_panel.update_single_exchange(
            None,
            f"**(=^･ω･^=) ¡Mira esto!**\n{msg}",
            streaming=False,
            metrics="🐾 michi aleatorio · randomcatapi",
        )
        self._popup_panel.set_cards([card])
        self._orb.spawn_particles("🐾", 3)
        self._orb.spawn_particles("nya~", 2)
        self._set_state_mode("happy", custom_icon="🐱", duration_ms=2600)
        self._schedule_random_cat()

    # ── Cierre limpio ─────────────────────────────────────────────────────────
    def _shutdown(self):
        self._cleanup()
        QApplication.quit()

    def _cleanup(self):
        try:
            self._conversation_mode = False
            self._solo_timer.stop()
            self._cat_timer.stop()
            self._reminder_tick_timer.stop()
            self._topmost_timer.stop()
            self._popup_panel.hide()
            if self._listen_thread is not None and self._listen_thread.isRunning():
                self._listen_thread.cancel()
                self._listen_thread.wait(1200)
            if self._worker is not None and self._worker.isRunning():
                self._worker.abort()
                self._worker.wait(1200)
            if self._voice_io is not None:
                self._voice_io.stop_speaking()
                self._voice_io.close()
            bridge = self.services.get("calls") if self.services else None
            if bridge is not None:
                bridge.close()
        except Exception as exc:
            print(f"Al cerrar: {exc}", file=sys.stderr)
        finally:
            self._voice_io = None

    def closeEvent(self, event):
        self._cleanup()
        super().closeEvent(event)


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    pet = CloePet()
    screen = app.primaryScreen().availableGeometry()
    pet.move(screen.right() - pet.width() - 28, screen.bottom() - pet.height() - 40)
    pet.show()
    sys.exit(app.exec())
