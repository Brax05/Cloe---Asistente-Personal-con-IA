"""
Módulo 3: Control del PC en Linux para Cloe.
- Control de volumen del sistema (PipeWire wpctl / PulseAudio pactl / ALSA amixer)
- Control multimedia local vía MPRIS / playerctl (sin abrir navegador)
- Apertura de aplicaciones de escritorio en Linux
- Diagnóstico en tiempo real del sistema (batería, disco, RAM, CPU, temperatura, uptime)
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
from typing import Optional


# ── 1. Control de Volumen del Sistema ─────────────────────────────────────────
def get_system_volume() -> Optional[tuple[int, bool]]:
    """Devuelve (porcentaje_0_a_150, esta_muteado) usando wpctl o pactl."""
    if shutil.which("wpctl"):
        try:
            res = subprocess.run(
                ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
                capture_output=True,
                text=True,
                timeout=2.0,
                check=False,
            )
            out = (res.stdout or "").strip()
            # Ejemplo: "Volume: 0.65" o "Volume: 0.65 [MUTED]"
            m = re.search(r"Volume:\s*([0-9.]+)", out)
            if m:
                pct = int(round(float(m.group(1)) * 100))
                muted = "MUTED" in out.upper()
                return pct, muted
        except Exception:
            pass

    if shutil.which("pactl"):
        try:
            res = subprocess.run(
                ["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
                capture_output=True,
                text=True,
                timeout=2.0,
                check=False,
            )
            m = re.search(r"(\d+)\s*%", res.stdout or "")
            mute_res = subprocess.run(
                ["pactl", "get-sink-mute", "@DEFAULT_SINK@"],
                capture_output=True,
                text=True,
                timeout=2.0,
                check=False,
            )
            if m:
                pct = int(m.group(1))
                muted = "yes" in (mute_res.stdout or "").lower() or "sí" in (mute_res.stdout or "").lower()
                return pct, muted
        except Exception:
            pass
    return None


def set_system_volume(action: str, value: int = 10) -> str:
    """
    Ajusta el volumen del sistema en Linux.
    action: 'up' | 'down' | 'set' | 'mute' | 'unmute' | 'status'
    """
    value = max(0, min(120, int(value)))

    if action == "status":
        info = get_system_volume()
        if info is None:
            return "No pude leer el nivel de volumen del sistema."
        pct, muted = info
        estado = "silenciado (mute)" if muted else "activo"
        return f"El volumen actual del sistema está al {pct}% ({estado})."

    if shutil.which("wpctl"):
        try:
            if action == "mute":
                subprocess.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1"], timeout=2.0, check=False)
            elif action == "unmute":
                subprocess.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"], timeout=2.0, check=False)
            elif action == "set":
                subprocess.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"], timeout=2.0, check=False)
                subprocess.run(
                    ["wpctl", "set-volume", "-l", "1.2", "@DEFAULT_AUDIO_SINK@", f"{value}%"],
                    timeout=2.0,
                    check=False,
                )
            elif action == "up":
                subprocess.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"], timeout=2.0, check=False)
                subprocess.run(
                    ["wpctl", "set-volume", "-l", "1.2", "@DEFAULT_AUDIO_SINK@", f"{value}%+"],
                    timeout=2.0,
                    check=False,
                )
            elif action == "down":
                subprocess.run(
                    ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{value}%-"],
                    timeout=2.0,
                    check=False,
                )
            info = get_system_volume()
            if info:
                pct, muted = info
                if muted:
                    return f"Volumen del sistema silenciado ({pct}%)."
                return f"Volumen del sistema ajustado al {pct}%."
            return "Volumen del sistema ajustado correctamente."
        except Exception:
            pass

    if shutil.which("pactl"):
        try:
            if action == "mute":
                subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"], timeout=2.0, check=False)
            elif action == "unmute":
                subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"], timeout=2.0, check=False)
            elif action == "set":
                subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"], timeout=2.0, check=False)
                subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{value}%"], timeout=2.0, check=False)
            elif action == "up":
                subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"], timeout=2.0, check=False)
                subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"+{value}%"], timeout=2.0, check=False)
            elif action == "down":
                subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"-{value}%"], timeout=2.0, check=False)
            info = get_system_volume()
            if info:
                pct, muted = info
                return f"Volumen del sistema ajustado al {pct}%{' (silenciado)' if muted else ''}."
            return "Volumen del sistema ajustado."
        except Exception:
            pass

    return "No encontré wpctl ni pactl para controlar el volumen."


# ── 2. Apertura de Aplicaciones de Escritorio en Linux ────────────────────────
_APP_CATALOG: list[tuple[tuple[str, ...], str, list[list[str]]]] = [
    (
        ("vscode", "vs code", "visual studio code", "editor de código", "editor de codigo", "code"),
        "Visual Studio Code",
        [["code"], ["codium"], ["flatpak", "run", "com.visualstudio.code"]],
    ),
    (
        ("firefox", "navegador firefox"),
        "Firefox",
        [["firefox"], ["flatpak", "run", "org.mozilla.firefox"]],
    ),
    (
        ("chrome", "google chrome", "chromium", "brave", "navegador"),
        "Navegador Web",
        [["google-chrome"], ["google-chrome-stable"], ["brave-browser"], ["chromium"], ["firefox"], ["xdg-open", "https://www.google.com"]],
    ),
    (
        ("terminal", "consola", "konsole", "gnome-terminal", "alacritty", "kitty", "tilix"),
        "Terminal",
        [["gnome-terminal"], ["ptyxis"], ["kgx"], ["konsole"], ["xfce4-terminal"], ["kitty"], ["alacritty"], ["x-terminal-emulator"], ["xterm"]],
    ),
    (
        ("archivos", "mis archivos", "explorador de archivos", "carpeta personal", "nautilus", "dolphin", "thunar", "nemo", "gestor de archivos"),
        "Gestor de Archivos",
        [["nautilus"], ["nemo"], ["dolphin"], ["thunar"], ["pcmanfm"], ["xdg-open", os.path.expanduser("~")]],
    ),
    (
        ("calculadora", "calc"),
        "Calculadora",
        [["gnome-calculator"], ["kcalc"], ["galculator"], ["mate-calc"]],
    ),
    (
        ("spotify",),
        "Spotify (App de Escritorio)",
        [["spotify"], ["flatpak", "run", "com.spotify.Client"]],
    ),
    (
        ("discord",),
        "Discord",
        [["discord"], ["flatpak", "run", "com.discordapp.Discord"], ["vesktop"]],
    ),
    (
        ("telegram",),
        "Telegram",
        [["telegram-desktop"], ["flatpak", "run", "org.telegram.desktop"]],
    ),
    (
        ("steam",),
        "Steam",
        [["steam"], ["flatpak", "run", "com.valvesoftware.Steam"]],
    ),
    (
        ("obs", "obs studio"),
        "OBS Studio",
        [["obs"], ["flatpak", "run", "com.obsproject.Studio"]],
    ),
    (
        ("vlc", "reproductor de video"),
        "VLC",
        [["vlc"], ["flatpak", "run", "org.videolan.VLC"]],
    ),
    (
        ("monitor del sistema", "monitor de sistema", "administrador de tareas", "htop"),
        "Monitor del Sistema",
        [["gnome-system-monitor"], ["ksysguard"], ["plasma-systemmonitor"], ["xfce4-taskmanager"]],
    ),
    (
        ("configuración", "configuracion", "ajustes del sistema", "panel de control"),
        "Configuración del Sistema",
        [["gnome-control-center"], ["systemsettings"], ["xfce4-settings-manager"]],
    ),
    (
        ("editor de texto", "bloc de notas", "gedit", "kate"),
        "Editor de Texto",
        [["gnome-text-editor"], ["gedit"], ["kate"], ["mousepad"], ["xed"]],
    ),
]


def launch_desktop_app(target_query: str) -> str:
    """Busca y lanza una aplicación de escritorio en Linux sin bloquear a Cloe."""
    q = (target_query or "").strip().lower()
    if not q:
        return "No especificaste qué aplicación abrir."

    for aliases, display_name, cmd_candidates in _APP_CATALOG:
        if any(alias == q or alias in q for alias in aliases):
            for cmd in cmd_candidates:
                bin_name = cmd[0]
                if not shutil.which(bin_name):
                    continue
                if bin_name == "flatpak" and len(cmd) >= 3:
                    # Verificar si el flatpak existe
                    chk = subprocess.run(
                        ["flatpak", "info", cmd[2]],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=1.5,
                        check=False,
                    )
                    if chk.returncode != 0:
                        continue
                try:
                    subprocess.Popen(
                        cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                    return f"Aplicación abierta con éxito: {display_name} ({' '.join(cmd)})."
                except Exception:
                    continue
            return f"No encontré {display_name} instalado en tu sistema."

    # Intento directo seguro si el nombre coincide con un binario conocido en /usr/bin
    clean_bin = re.sub(r"[^a-z0-9_\-]", "", q.split()[0])
    if clean_bin and clean_bin not in ("rm", "dd", "sudo", "sh", "bash", "kill", "pkill", "reboot", "shutdown"):
        path_bin = shutil.which(clean_bin)
        if path_bin and (path_bin.startswith("/usr/bin/") or path_bin.startswith("/snap/bin/")):
            try:
                subprocess.Popen(
                    [clean_bin],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                return f"Aplicación '{clean_bin}' iniciada."
            except Exception:
                pass

    return f"No encontré una aplicación llamada '{target_query}' instalada en el escritorio."


# ── 3. Diagnóstico en Vivo del Sistema (Batería, Disco, RAM, CPU, Temperatura) ─
def get_system_status_summary() -> str:
    """Recopila el estado real del PC en Linux: Batería, RAM, Disco, CPU y Temperatura."""
    parts: list[str] = []

    # 1. Batería
    bat_dirs = sorted(glob.glob("/sys/class/power_supply/BAT*"))
    if bat_dirs:
        try:
            bdir = bat_dirs[0]
            cap_path = os.path.join(bdir, "capacity")
            stat_path = os.path.join(bdir, "status")
            cap = open(cap_path, "r", encoding="utf-8").read().strip() if os.path.exists(cap_path) else "?"
            raw_stat = open(stat_path, "r", encoding="utf-8").read().strip() if os.path.exists(stat_path) else ""
            stat_es = {
                "Charging": "cargando ⚡",
                "Discharging": "descargándose (en batería)",
                "Full": "carga completa (100%)",
                "Not charging": "conectada a corriente (sin cargar)",
            }.get(raw_stat, raw_stat)
            parts.append(f"- Batería: {cap}% ({stat_es})")
        except Exception:
            pass
    else:
        parts.append("- Batería: Conectado a corriente directa / sin batería detectada")

    # 2. Memoria RAM (/proc/meminfo)
    try:
        meminfo: dict[str, int] = {}
        with open("/proc/meminfo", "r", encoding="utf-8") as fh:
            for line in fh:
                if ":" in line:
                    k, v = line.split(":", 1)
                    nums = re.findall(r"\d+", v)
                    if nums:
                        meminfo[k.strip()] = int(nums[0])
        total_kb = meminfo.get("MemTotal", 0)
        avail_kb = meminfo.get("MemAvailable", 0)
        if total_kb > 0:
            used_gb = (total_kb - avail_kb) / (1024 * 1024)
            total_gb = total_kb / (1024 * 1024)
            avail_gb = avail_kb / (1024 * 1024)
            pct_ram = int(round(((total_kb - avail_kb) / total_kb) * 100))
            parts.append(f"- Memoria RAM: {used_gb:.1f} GB usados de {total_gb:.1f} GB ({pct_ram}% en uso, {avail_gb:.1f} GB libres)")
    except Exception:
        pass

    # 3. Espacio en Disco (/)
    try:
        du = shutil.disk_usage(os.path.expanduser("~"))
        free_gb = du.free / (1024**3)
        total_gb = du.total / (1024**3)
        used_pct = int(round((du.used / du.total) * 100))
        parts.append(f"- Espacio en disco: {free_gb:.1f} GB libres de {total_gb:.1f} GB totales ({used_pct}% ocupado)")
    except Exception:
        pass

    # 4. Carga de CPU y Uptime
    try:
        with open("/proc/loadavg", "r", encoding="utf-8") as fh:
            load_1m = float(fh.read().split()[0])
        cores = os.cpu_count() or 1
        cpu_approx = min(100, int(round((load_1m / cores) * 100)))
        parts.append(f"- Carga de CPU: ~{cpu_approx}% (loadavg {load_1m:.2f} en {cores} hilos)")
    except Exception:
        pass

    # 5. Temperatura de CPU / sensores térmicos
    try:
        temps_c: list[float] = []
        for tpath in glob.glob("/sys/class/thermal/thermal_zone*/temp"):
            try:
                val = int(open(tpath, "r", encoding="utf-8").read().strip())
                if 20000 <= val <= 115000:
                    temps_c.append(val / 1000.0)
            except Exception:
                continue
        if temps_c:
            parts.append(f"- Temperatura máxima sensores: {max(temps_c):.0f}°C")
    except Exception:
        pass

    # 6. Volumen actual
    vol_info = get_system_volume()
    if vol_info is not None:
        vpct, vmuted = vol_info
        parts.append(f"- Volumen del sistema: {vpct}% ({'silenciado' if vmuted else 'activo'})")

    return "\n".join(parts)


# ── 4. Detector y Ejecutor de Intenciones de Control del PC ───────────────────
def handle_pc_control_intent(user_text: str) -> Optional[str]:
    """
    Detecta si el usuario pide controlar el volumen, abrir una app o consultar el estado del PC.
    Si aplica, ejecuta la acción y devuelve una nota de sistema con el resultado real para que Cloe responda.
    """
    raw = (user_text or "").strip()
    if not raw:
        return None
    low = raw.lower()

    # A) Control de Volumen
    if re.search(
        r"\b(sube|súbele|subele|aumenta|más|mas|baja|bájale|bajale|reduce|menos|pon|ajusta|deja|silencia|mutea|quita el silencio|activa el sonido|en cuánto está|en cuanto esta|nivel de)\b.*\b(volumen|audio|sonido)\b"
        r"|\b(volumen)\s+(?:al?\s+)?(\d{1,3})\s*%?"
        r"|\b(mutea|silencia)\s+(?:el\s+)?(pc|computador|ordenador|sistema)\b",
        low,
    ):
        num_match = re.search(r"(\d{1,3})\s*%?", low)
        if any(w in low for w in ("quita el silencio", "desmutea", "activa el sonido", "unmute")):
            res = set_system_volume("unmute")
        elif any(w in low for w in ("silencia", "mutea", "pon mute", "sin sonido")):
            res = set_system_volume("mute")
        elif any(w in low for w in ("en cuánto", "en cuanto", "qué nivel", "que nivel", "cuál es el volumen", "cual es el volumen")):
            res = set_system_volume("status")
        elif any(w in low for w in ("sube", "súbele", "subele", "aumenta", "más volumen", "mas volumen")):
            step = int(num_match.group(1)) if num_match else 10
            # Si dice "sube el volumen a 80", es un 'set'
            if re.search(r"\b(a|al)\s+\d{1,3}", low):
                res = set_system_volume("set", step)
            else:
                res = set_system_volume("up", step)
        elif any(w in low for w in ("baja", "bájale", "bajale", "reduce", "menos volumen")):
            step = int(num_match.group(1)) if num_match else 10
            if re.search(r"\b(a|al)\s+\d{1,3}", low):
                res = set_system_volume("set", step)
            else:
                res = set_system_volume("down", step)
        elif num_match:
            res = set_system_volume("set", int(num_match.group(1)))
        else:
            res = set_system_volume("status")
        return f"[Acción del sistema ejecutada en Linux: {res} Confírmaselo al usuario con naturalidad.]"

    # B) Abrir Aplicaciones de Escritorio
    open_match = re.search(
        r"^\s*(?:cloe[\s,]+)?(?:por favor\s+)?(?:abre|ábreme|abreme|inicia|ejecuta|lanza)\s+(?:la\s+aplicaci[oó]n\s+|el\s+programa\s+|la\s+app\s+|el\s+|la\s+|mis\s+)?(.+?)\s*[.!?]*$",
        low,
    )
    if open_match:
        app_target = open_match.group(1).strip()
        # Evitar falsos positivos como "abre mi calendario" o "abre mi correo"
        if not any(k in app_target for k in ("correo", "gmail", "calendario", "agenda", "burbuja", "historial")):
            res = launch_desktop_app(app_target)
            return f"[Acción del sistema ejecutada en Linux: {res} Avísale al usuario de forma breve y cálida.]"

    # C) Consultas sobre el Estado del PC (Batería, Disco, RAM, CPU, Temperatura)
    if re.search(
        r"\b(cuánta batería|cuanta bateria|nivel de batería|nivel de bateria|estado de la batería|batería me queda|bateria me queda"
        r"|espacio libre|espacio en disco|cuánto disco|cuanto disco|almacenamiento libre"
        r"|cuánta ram|cuanta ram|uso de ram|uso de memoria|uso de cpu|temperatura del pc|temperatura de la cpu"
        r"|estado del sistema|estado de mi pc|cómo está mi pc|como esta mi pc|recursos del sistema)\b",
        low,
    ):
        stats = get_system_status_summary()
        return (
            f"[Datos reales en vivo del PC Linux del usuario]:\n{stats}\n"
            "[Instrucción: Responde a la pregunta del usuario usando exactamente estos datos reales de su PC.]"
        )

    return None
