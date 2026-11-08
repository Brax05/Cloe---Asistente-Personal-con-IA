"""Módulo 2: Visión de Pantalla y Portapapeles Inteligente para Cloe."""

from __future__ import annotations

import base64
import os
import re
import select
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse

# ── 1. Detección y Lectura de Portapapeles Inteligente ────────────────────────

_CLIPBOARD_PATTERNS = [
    re.compile(r"\b(?:portapapeles|clipboard)\b", re.IGNORECASE),
    re.compile(r"\blo\s+que\s+(?:acabo\s+de\s+)?copi(?:é|e|ar)\b", re.IGNORECASE),
    re.compile(r"\blo\s+copiado\b", re.IGNORECASE),
    re.compile(r"\b(?:traduce|resume|explica|analiza|corrige|revisa|lee)\s+lo\s+que\s+copi(?:é|e)\b", re.IGNORECASE),
    re.compile(r"\btexte?\s+copiado\b", re.IGNORECASE),
    re.compile(r"\bcódigo\s+que\s+copi(?:é|e)\b", re.IGNORECASE),
    re.compile(r"\bcodigo\s+que\s+copi(?:é|e)\b", re.IGNORECASE),
]


def is_clipboard_request(user_text: str) -> bool:
    """Devuelve True si el usuario pide hacer algo con el contenido de su portapapeles."""
    txt = (user_text or "").strip()
    if not txt:
        return False
    return any(pat.search(txt) for pat in _CLIPBOARD_PATTERNS)


def read_clipboard_text() -> str:
    """Lee el texto actual del portapapeles en Linux (Qt6, Wayland wl-paste o X11 xclip/xsel)."""
    try:
        from PyQt6.QtGui import QGuiApplication

        app = QGuiApplication.instance()
        if app is not None:
            cb = app.clipboard()
            if cb is not None:
                txt = (cb.text() or "").strip()
                if txt:
                    return txt
    except Exception:
        pass

    cmds = [
        ["wl-paste", "--no-newline"],
        ["xclip", "-o", "-selection", "clipboard"],
        ["xclip", "-o"],
        ["xsel", "-ob"],
    ]
    for cmd in cmds:
        if shutil.which(cmd[0]):
            try:
                out = subprocess.check_output(
                    cmd, stderr=subprocess.DEVNULL, timeout=1.5
                ).decode("utf-8", errors="replace").strip()
                if out:
                    return out
            except Exception:
                continue
    return ""


# ── 2. Detección y Captura de Visión de Pantalla ──────────────────────────────

_SCREEN_VISION_PATTERNS = [
    re.compile(
        r"\b(?:mira|ve|ver|observa|analiza|revisa|lee|describe|explica|checa|fíjate|fijate)\s+"
        r"(?:en\s+)?(?:mi\s+|la\s+)?pantalla\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:qué|que)\s+(?:ves|vez|hay|dice|aparece|sale|tengo|estoy\s+viendo)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ayúdame|ayudame)\s+con\s+(?:este\s+|el\s+|esto\s+)?(?:error|código|codigo|problema|pantalla)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bcaptura\s+(?:de\s+)?(?:mi\s+|la\s+)?pantalla\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:en\s+mi\s+pantalla|en\s+la\s+pantalla)\b",
        re.IGNORECASE,
    ),
]


def is_screen_vision_request(user_text: str) -> bool:
    """Devuelve True si el usuario le pide a Cloe mirar o analizar su pantalla."""
    txt = (user_text or "").strip()
    if not txt:
        return False
    return any(pat.search(txt) for pat in _SCREEN_VISION_PATTERNS)


def _is_image_mostly_black(qimg) -> bool:
    """
    Detecta únicamente si la captura salió 100% vacía/negra pura (fallo de permiso en Wayland).
    No rechaza escritorios en modo oscuro (donde hay píxeles grises/texto).
    """
    if qimg.isNull() or qimg.width() < 10 or qimg.height() < 10:
        return True
    sample_w = min(64, qimg.width())
    sample_h = min(64, qimg.height())
    scaled = qimg.scaled(sample_w, sample_h)
    non_zero = 0
    for y in range(sample_h):
        for x in range(sample_w):
            col = scaled.pixelColor(x, y)
            if col.red() > 3 or col.green() > 3 or col.blue() > 3:
                non_zero += 1
                if non_zero >= 8:
                    return False
    return True


_PORTAL_SCREENSHOT_SCRIPT = """
import sys, urllib.parse
from gi.repository import Gio, GLib

loop = GLib.MainLoop()
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
out = []

def on_sig(conn, sender, path, iface, sig, params, *args):
    try:
        resp, results = params.unpack()
        if resp == 0 and "uri" in results:
            u = str(results["uri"])
            if u.startswith("file://"):
                out.append(urllib.parse.unquote(u[7:]))
    except Exception:
        pass
    loop.quit()

sub = bus.signal_subscribe(
    None,
    "org.freedesktop.portal.Request",
    "Response",
    None,
    None,
    Gio.DBusSignalFlags.NONE,
    on_sig,
)
try:
    bus.call_sync(
        "org.freedesktop.portal.Desktop",
        "/org/freedesktop/portal/desktop",
        "org.freedesktop.portal.Screenshot",
        "Screenshot",
        GLib.Variant("(sa{sv})", ("", {"interactive": GLib.Variant("b", False)})),
        None,
        Gio.DBusCallFlags.NONE,
        4000,
        None,
    )
    GLib.timeout_add(12000, loop.quit)
    loop.run()
finally:
    bus.signal_unsubscribe(sub)

if out:
    sys.stdout.write(out[0])
""".strip()


def _capture_via_xdg_portal_gdbus() -> str | None:
    """
    Captura la pantalla usando org.freedesktop.portal.Screenshot manteniendo viva la misma conexión D-Bus
    mediante el Python del sistema (/usr/bin/python3 con gi.repository.Gio).
    Funciona en Wayland (GNOME, KDE, Hyprland, Sway) y X11 sin depender del .venv.
    """
    for py_bin in ("/usr/bin/python3", "/bin/python3", "python3", sys.executable):
        if not py_bin or (py_bin.startswith("/") and not os.path.exists(py_bin)):
            continue
        try:
            out = subprocess.check_output(
                [py_bin, "-c", _PORTAL_SCREENSHOT_SCRIPT],
                stderr=subprocess.DEVNULL,
                timeout=13.0,
            ).decode("utf-8", errors="replace").strip()
            if out and os.path.exists(out):
                return out
        except Exception:
            continue
    return None


def _capture_from_clipboard_image():
    """Si hay una captura/imagen recién copiada en el portapapeles, la devuelve como QImage."""
    from PyQt6.QtGui import QGuiApplication, QImage

    try:
        app = QGuiApplication.instance()
        if app is not None:
            cb = app.clipboard()
            if cb is not None:
                img = cb.image()
                if not img.isNull() and not _is_image_mostly_black(img):
                    return img
    except Exception:
        pass

    for cmd in (
        ["wl-paste", "--type", "image/png"],
        ["xclip", "-selection", "clipboard", "-t", "image/png", "-o"],
    ):
        if shutil.which(cmd[0]):
            try:
                raw = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=1.5)
                if raw and len(raw) > 200:
                    img = QImage.fromData(raw)
                    if not img.isNull() and not _is_image_mostly_black(img):
                        return img
            except Exception:
                continue
    return QImage()


def capture_screen_jpeg(max_width: int = 1280, quality: int = 80) -> tuple[bytes, str]:
    """
    Captura la pantalla completa en Linux (Wayland o X11) probando múltiples métodos
    y devuelve:
      (jpeg_bytes, base64_jpeg_str)
    Si no se pudo capturar, devuelve (b"", "").
    """
    from PyQt6.QtCore import QBuffer, QIODevice, Qt
    from PyQt6.QtGui import QGuiApplication, QImage

    qimg = QImage()
    is_wayland = bool(
        os.environ.get("WAYLAND_DISPLAY")
        or "wayland" in (os.environ.get("XDG_SESSION_TYPE", "") or "").lower()
    )
    tmp_path = os.path.join(tempfile.gettempdir(), f"cloe_screen_{os.getpid()}.png")

    # 1. En X11 puro, grabWindow(0) es instantáneo
    if not is_wayland:
        try:
            screen = QGuiApplication.primaryScreen()
            if screen is not None:
                pix = screen.grabWindow(0)
                cand = pix.toImage()
                if not _is_image_mostly_black(cand):
                    qimg = cand
        except Exception:
            pass

    # 2. En Wayland (o si X11 falló), usar XDG Desktop Portal vía /usr/bin/gdbus
    if qimg.isNull():
        portal_file = _capture_via_xdg_portal_gdbus()
        if portal_file:
            try:
                cand = QImage(portal_file)
                if not _is_image_mostly_black(cand):
                    qimg = cand
            finally:
                try:
                    os.remove(portal_file)
                except Exception:
                    pass

    # 3. Herramientas CLI nativas (GNOME DBus, grim, spectacle, gnome-screenshot, scrot, ffmpeg)
    if qimg.isNull():
        display = os.environ.get("DISPLAY", ":0")
        cli_tools = [
            [
                "gdbus", "call", "--session",
                "--dest", "org.gnome.Shell.Screenshot",
                "--object-path", "/org/gnome/Shell/Screenshot",
                "--method", "org.gnome.Shell.Screenshot.Screenshot",
                "false", "false", tmp_path,
            ],
            ["grim", tmp_path],
            ["spectacle", "-b", "-n", "-o", tmp_path],
            ["gnome-screenshot", "-f", tmp_path],
            ["xfce4-screenshooter", "-f", "-s", tmp_path],
            ["maim", tmp_path],
            ["scrot", "-o", tmp_path],
            ["import", "-window", "root", tmp_path],
            [
                "ffmpeg", "-y", "-loglevel", "quiet",
                "-f", "x11grab", "-i", display,
                "-frames:v", "1", tmp_path,
            ],
        ]

        for cmd in cli_tools:
            if not shutil.which(cmd[0]):
                continue
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                subprocess.run(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=3.0,
                    check=False,
                )
                if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 400:
                    cand = QImage(tmp_path)
                    if not _is_image_mostly_black(cand):
                        qimg = cand
                        break
            except Exception:
                continue
            finally:
                try:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
                except Exception:
                    pass

    # 4. Intentar grabWindow(0) sobre XWayland
    if qimg.isNull():
        try:
            screen = QGuiApplication.primaryScreen()
            if screen is not None:
                pix = screen.grabWindow(0)
                cand = pix.toImage()
                if not _is_image_mostly_black(cand):
                    qimg = cand
        except Exception:
            pass

    # 5. Respaldo: si el usuario hizo una captura con Impr Pant al portapapeles
    if qimg.isNull():
        qimg = _capture_from_clipboard_image()

    if qimg.isNull():
        return b"", ""

    if qimg.width() > max_width:
        qimg = qimg.scaledToWidth(max_width, Qt.TransformationMode.SmoothTransformation)

    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    qimg.save(buf, "JPEG", quality)
    jpeg_bytes = bytes(buf.data())
    buf.close()

    if not jpeg_bytes:
        return b"", ""
    b64_str = base64.b64encode(jpeg_bytes).decode("ascii")
    return jpeg_bytes, b64_str


def get_active_window_context() -> str:
    """Obtiene el título de la ventana activa como apoyo adicional."""
    info_parts: list[str] = []
    for cmd in (
        ["xdotool", "getactivewindow", "getwindowname"],
        ["hyprctl", "activewindow", "-j"],
    ):
        if shutil.which(cmd[0]):
            try:
                out = subprocess.check_output(
                    cmd, stderr=subprocess.DEVNULL, timeout=1.0
                ).decode("utf-8", errors="ignore").strip()
                if out:
                    info_parts.append(f"Ventana activa: {out[:200]}")
                    break
            except Exception:
                pass
    return "\n".join(info_parts)
