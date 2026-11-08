import json
import os
import re
import shlex
import subprocess
from typing import Callable

HOME_DIR = os.path.expanduser("~")
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Estado en memoria para comandos que requieren autorización explícita del usuario
_PENDING_COMMAND: dict | None = None
# Última tarjeta visual generada por el módulo de terminal para mostrar en la burbuja de Cloe
_LAST_TERMINAL_CARD: dict | None = None


def pop_last_terminal_card() -> dict | None:
    """Extrae y limpia la última tarjeta visual de terminal para la GUI."""
    global _LAST_TERMINAL_CARD
    card = _LAST_TERMINAL_CARD
    _LAST_TERMINAL_CARD = None
    return card


def get_pending_command() -> dict | None:
    """Devuelve el comando que está esperando autorización del usuario, si existe."""
    return _PENDING_COMMAND


def _resolve_user_folder(folder_hint: str) -> str:
    """Resuelve nombres comunes de carpetas de usuario en español/inglés a su ruta real en Linux."""
    low = folder_hint.strip().lower()
    candidates_map = {
        "descargas": ["Descargas", "Downloads"],
        "downloads": ["Descargas", "Downloads"],
        "documentos": ["Documentos", "Documents"],
        "documents": ["Documentos", "Documents"],
        "escritorio": ["Escritorio", "Desktop"],
        "desktop": ["Escritorio", "Desktop"],
        "imagenes": ["Imágenes", "Imagenes", "Pictures"],
        "imágenes": ["Imágenes", "Imagenes", "Pictures"],
        "pictures": ["Imágenes", "Imagenes", "Pictures"],
        "musica": ["Música", "Musica", "Music"],
        "música": ["Música", "Musica", "Music"],
        "videos": ["Vídeos", "Videos"],
        "vídeos": ["Vídeos", "Videos"],
    }
    for key, names in candidates_map.items():
        if key in low:
            for name in names:
                full = os.path.join(HOME_DIR, name)
                if os.path.isdir(full):
                    return full
            return os.path.join(HOME_DIR, names[0])
    return HOME_DIR


# ── Detección de Intención de Terminal y Autorización ─────────────────────────

_CONFIRM_YES_PATTERNS = re.compile(
    r"^\s*(?:s[ií]|s[ií]\s+autorizo|autorizo(?:\s+el\s+comando)?|autorizar|"
    r"confirmo|confirmar|adelante|hazlo|ejec[uú]talo|dale|ok\s+ejecuta)\s*[.!]*\s*$",
    re.IGNORECASE,
)

_CONFIRM_NO_PATTERNS = re.compile(
    r"^\s*(?:no|cancelar(?:\s+comando)?|cancela|no\s+lo\s+hagas|detente|abortar)\s*[.!]*\s*$",
    re.IGNORECASE,
)

_TERMINAL_INTENT_PATTERNS = [
    r"\b(?:en\s+la\s+terminal|por\s+terminal|usa\s+la\s+terminal|desde\s+la\s+terminal|"
    r"en\s+la\s+consola|ejecuta\s+el\s+comando|corre\s+el\s+comando|ejecuta\s+en\s+bash|"
    r"comando\s+de\s+linux|ejecutar\s+comando)\b",
    r"\b(?:qu[eé]\s+archivos\s+hay|lista\s+(?:los\s+)?archivos|mostrar\s+archivos|"
    r"listar\s+carpeta|qu[eé]\s+hay\s+en\s+mi\s+carpeta|ver\s+archivos\s+de)\b",
    r"\b(?:crea\s+una\s+carpeta|crear\s+carpeta|crea\s+un\s+directorio|"
    r"crea\s+un\s+archivo|crear\s+archivo)\b",
    r"\b(?:borra\s+(?:el\s+)?archivo|elimina\s+(?:el\s+)?archivo|borrar\s+archivo|"
    r"eliminar\s+archivo|borra\s+la\s+carpeta|elimina\s+la\s+carpeta)\b",
    r"\b(?:busca\s+(?:el\s+)?archivo|buscar\s+archivo|encuentra\s+(?:el\s+)?archivo)\b",
    r"\b(?:qu[eé]\s+puertos\s+est[aá]n\s+abiertos|puertos\s+en\s+uso|mi\s+direcci[oó]n\s+ip|"
    r"cu[aá]l\s+es\s+mi\s+ip|qu[eé]\s+procesos\s+consumen|procesos\s+activos|"
    r"cu[aá]nto\s+pesa\s+la\s+carpeta|espacio\s+de\s+la\s+carpeta)\b",
    r"\b(?:haz\s+un\s+git\s+|ejecuta\s+git\s+|estado\s+de\s+git|git\s+status|git\s+log)\b",
]


def is_terminal_confirmation_reply(user_text: str) -> str | None:
    """
    Si hay un comando esperando autorización, detecta si el usuario dijo 'autorizo' ('yes')
    o 'cancelar' ('no'). Devuelve 'yes', 'no' o None.
    """
    if _PENDING_COMMAND is None:
        return None
    cleaned = (user_text or "").strip()
    if _CONFIRM_YES_PATTERNS.match(cleaned):
        return "yes"
    if _CONFIRM_NO_PATTERNS.match(cleaned):
        return "no"
    return None


def is_terminal_request(user_text: str) -> bool:
    """Detecta si el usuario le está pidiendo a Cloe realizar una acción en la terminal de Linux."""
    text = (user_text or "").strip()
    if not text:
        return False
    low = text.lower()
    for pat in _TERMINAL_INTENT_PATTERNS:
        if re.search(pat, low, re.IGNORECASE):
            return True
    # Si escribe directamente "ejecuta `comando`" o "terminal: comando"
    if low.startswith(("terminal:", "bash:", "cmd:", "comando:")):
        return True
    return False


# ── Clasificador de Seguridad de 3 Niveles (SAFE / CONFIRM / BLOCKED) ─────────

# Nivel 1: Comandos catastróficos o destructivos del sistema -> BLOQUEADOS SIEMPRE
_BLOCKED_REGEXES: list[tuple[re.Pattern, str]] = [
    (
        re.compile(r"\b(?:mkfs|wipefs|fdisk|parted|sfdisk|shred)\b", re.I),
        "Formatear, particionar o destruir discos/particiones está estrictamente prohibido.",
    ),
    (
        re.compile(r"\bdd\b.*\bof\s*=\s*/dev/", re.I),
        "Escribir directamente sobre dispositivos de bloque (/dev/*) está prohibido.",
    ),
    (
        re.compile(r":\s*\(\s*\)\s*\{.*:\s*\|\s*:.*\}\s*;", re.I),
        "Las bombas fork están bloqueadas por seguridad.",
    ),
    (
        re.compile(r"(?:^|[;&|]\s*)(?:sudo\s+)?rm\s+.*--no-preserve-root", re.I),
        "Borrado de raíz del sistema bloqueado.",
    ),
    (
        re.compile(
            r"(?:^|[;&|]\s*)(?:sudo\s+)?rm\s+(?:-[a-zA-Z]*[rf][a-zA-Z]*\s+)+"
            r"(?:/|/\*|\~|\~/\*|\$HOME|\$HOME/\*|/home(?:/[^/\s]+)?/?|/etc|/usr|/var|/boot)\s*$",
            re.I,
        ),
        "Borrar el sistema operativo o tu directorio personal completo está estrictamente prohibido.",
    ),
    (
        re.compile(
            r"(?:^|[;&|]\s*)(?:sudo\s+)?rm\s+(?:-[a-zA-Z]*[rf][a-zA-Z]*\s+)*"
            r"(?:\~|\$HOME|/home/[^/\s]+)/(?:Documentos|Documents|Escritorio|Desktop|Descargas|Downloads|Im[aá]genes|Pictures)/?\*?\s*$",
            re.I,
        ),
        "Borrar tus carpetas principales (Documentos, Escritorio, Descargas o Imágenes) completas no está permitido.",
    ),
    (
        re.compile(r"\b(?:curl|wget)\b[^|]*\|\s*(?:sudo\s+)?(?:ba)?sh\b", re.I),
        "Descargar scripts de internet y ejecutarlos a ciegas en shell está bloqueado por seguridad.",
    ),
    (
        re.compile(r"\b(?:shutdown|reboot|poweroff|halt|init\s+[06])\b", re.I),
        "Apagar o reiniciar el equipo desde la terminal automática está bloqueado.",
    ),
    (
        re.compile(r">\s*/dev/(?:sd[a-z]|nvme\d|null\s+2>&1\s*<)", re.I),
        "Redirección destructiva hacia dispositivos del sistema bloqueada.",
    ),
    (
        re.compile(r"\b(?:chmod|chown)\s+-R\s+.*\s+/(?:\s|$)", re.I),
        "Cambiar permisos o propietarios recursivamente en la raíz (/) está prohibido.",
    ),
]

# Nivel 2: Comandos delicados que requieren AUTORIZACIÓN EXPLÍCITA antes de ejecutarse
_CONFIRM_REGEXES: list[tuple[re.Pattern, str]] = [
    (
        re.compile(r"(?:^|[;&|]\s*)(?:sudo|su|pkexec|doas)\b", re.I),
        "Usa privilegios de administrador (sudo/root).",
    ),
    (
        re.compile(r"(?:^|[;&|]\s*)(?:rm|rmdir|unlink|trash|trash-put)\b|\bgio\s+trash\b", re.I),
        "Elimina archivos o carpetas, lo cual requiere tu autorización.",
    ),
    (
        re.compile(r"(?:^|[;&|]\s*)mv\b", re.I),
        "Mueve o renombra archivos existentes.",
    ),
    (
        re.compile(r"(?:Documentos|Documents)", re.I),
        "Accede o modifica la carpeta de Documentos.",
    ),
    (
        re.compile(
            r"\b(?:apt|apt-get|dpkg|snap|flatpak|pacman|dnf|yum)\s+"
            r"(?:install|remove|purge|upgrade|dist-upgrade|autoremove|-S|-R)\b"
            r"|\b(?:pip|pip3|npm)\s+(?:install|uninstall)\b",
            re.I,
        ),
        "Instala, actualiza o desinstala paquetes del sistema.",
    ),
    (
        re.compile(r"\b(?:kill|pkill|killall)\b|\bsystemctl\s+(?:stop|restart|disable|mask)\b", re.I),
        "Detiene procesos o servicios en ejecución.",
    ),
    (
        re.compile(r"\b(?:chmod|chown|chgrp|sed\s+-i|truncate)\b", re.I),
        "Modifica permisos o edita archivos in-place.",
    ),
]

# Comandos de solo lectura sobre Documentos que siguen siendo seguros (listar/buscar sin borrar ni sobrescribir)
_READONLY_PREFIXES = (
    "ls", "find", "du", "stat", "file", "cat", "head", "tail", "wc", "grep", "rg", "tree",
)


def classify_command_safety(command: str) -> tuple[str, str]:
    """
    Evalúa un comando de terminal y devuelve:
      - ("BLOCKED", motivo) -> Prohibido, jamás se ejecuta.
      - ("CONFIRM", motivo) -> Requiere confirmación explícita del usuario.
      - ("SAFE", motivo)    -> Seguro para ejecución inmediata.
    """
    cmd = (command or "").strip()
    if not cmd:
        return "BLOCKED", "Comando vacío."

    # 1. Revisar bloqueos catastróficos primero
    for pattern, reason in _BLOCKED_REGEXES:
        if pattern.search(cmd):
            return "BLOCKED", reason

    # 2. Revisar si requiere confirmación del usuario
    for pattern, reason in _CONFIRM_REGEXES:
        if pattern.search(cmd):
            # Excepción: si solo es un `ls` o `du` de lectura en Documentos sin redirección `>` ni pipes destructivos
            if "Documentos" in reason and not any(op in cmd for op in (">", "|", ";", "&", "rm", "mv", "cp")):
                first_tok = cmd.split()[0].lower() if cmd.split() else ""
                if first_tok in _READONLY_PREFIXES:
                    continue
            return "CONFIRM", reason

    # 3. Si tiene redirecciones `>` que sobrescriben archivos (salvo /dev/null), pedir confirmación
    cleaned_devnull = re.sub(r"\d*>\s*/dev/null", "", cmd)
    if ">" in cleaned_devnull and not re.match(r"^\s*echo\b", cmd):
        return "CONFIRM", "Redirige salida hacia un archivo."

    return "SAFE", "Comando seguro de consulta o lectura."


# ── Ejecutor Controlado de Comandos ───────────────────────────────────────────

def execute_terminal_command(command: str, timeout: int = 12) -> dict:
    """Ejecuta un comando en bash con límite de tiempo y captura stdout/stderr sin colgar la GUI."""
    env = os.environ.copy()
    env["PAGER"] = "cat"
    env["GIT_PAGER"] = "cat"
    env["DEBIAN_FRONTEND"] = "noninteractive"

    cwd = PROJECT_DIR if "git " in command.lower() else HOME_DIR
    try:
        proc = subprocess.run(
            ["bash", "-c", command],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()
        combined = stdout if stdout else stderr
        if stdout and stderr:
            combined = f"{stdout}\n{stderr}"
        if not combined:
            combined = "(Comando ejecutado correctamente sin salida en texto)"
        if len(combined) > 2600:
            combined = combined[:2600] + "\n... [salida truncada]"
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "output": combined,
            "cwd": cwd,
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "returncode": -1,
            "output": f"Tiempo límite agotado ({timeout}s). El comando tardó demasiado o esperaba entrada interactiva.",
            "cwd": cwd,
        }
    except Exception as exc:
        return {
            "ok": False,
            "returncode": -1,
            "output": f"Error al ejecutar comando: {exc}",
            "cwd": cwd,
        }


# ── Traductor Rápido + Planificador IA de Comandos ────────────────────────────

def _fast_rule_translate(user_text: str) -> tuple[str, str] | None:
    """Traduce peticiones frecuentes de terminal de forma instantánea y determinista."""
    text = (user_text or "").strip()
    low = text.lower()

    # Prefijo directo: "terminal: ls -la" o comando entre backticks: ejecuta `ls -la`
    m_bt = re.search(r"(?:ejecuta|corre|terminal:?|comando:?)\s*`([^`]+)`", text, re.I)
    if m_bt:
        cmd = m_bt.group(1).strip()
        return cmd, f"Ejecutar `{cmd}`"

    for prefix in ("terminal:", "bash:", "cmd:", "comando:"):
        if low.startswith(prefix):
            cmd = text[len(prefix):].strip()
            if cmd:
                return cmd, f"Ejecutar `{cmd}`"

    # Listar archivos de una carpeta común
    if re.search(r"\b(?:qu[eé]\s+archivos\s+hay|lista\s+(?:los\s+)?archivos|ver\s+archivos|qu[eé]\s+hay\s+en)\b", low):
        for hint in ("descargas", "downloads", "documentos", "documents", "escritorio", "desktop", "imagenes", "imágenes", "musica", "música", "videos", "vídeos"):
            if hint in low:
                path = _resolve_user_folder(hint)
                return f"ls -lh {shlex.quote(path)} | head -n 35", f"Listar archivos en {path}"
        if "proyecto" in low or "cloe" in low or "aqu[ií]" in low:
            return f"ls -lh {shlex.quote(PROJECT_DIR)} | head -n 35", f"Listar archivos del proyecto ({PROJECT_DIR})"
        return f"ls -lh {shlex.quote(HOME_DIR)} | head -n 35", f"Listar archivos en tu carpeta personal ({HOME_DIR})"

    # Crear carpeta
    m_mkdir = re.search(
        r"\b(?:crea\s+una\s+carpeta|crear\s+carpeta|crea\s+un\s+directorio)\s+"
        r"(?:llamad[ao]\s+)?['\"]?([a-zA-Z0-9_\-\.]+)['\"]?"
        r"(?:\s+en\s+(?:mi\s+|el\s+|la\s+)?(escritorio|descargas|documentos|imagenes|imágenes|home|carpeta\s+personal))?",
        text,
        re.I,
    )
    if m_mkdir:
        folder_name = m_mkdir.group(1).strip()
        where_hint = m_mkdir.group(2) or ""
        base_dir = _resolve_user_folder(where_hint) if where_hint else HOME_DIR
        target_path = os.path.join(base_dir, folder_name)
        return f"mkdir -p {shlex.quote(target_path)} && ls -ld {shlex.quote(target_path)}", f"Crear carpeta {target_path}"

    # Puertos abiertos
    if re.search(r"\b(?:puertos\s+abiertos|puertos\s+en\s+uso|qu[eé]\s+puertos)\b", low):
        return "ss -tuln | head -n 25", "Ver puertos de red abiertos (ss -tuln)"

    # Dirección IP local
    if re.search(r"\b(?:cu[aá]l\s+es\s+mi\s+ip|mi\s+direcci[oó]n\s+ip)\b", low):
        return "ip -brief addr show", "Consultar direcciones IP de red"

    # Procesos que más consumen
    if re.search(r"\b(?:qu[eé]\s+procesos\s+consumen|procesos\s+que\s+m[aá]s\s+consumen|top\s+procesos)\b", low):
        return "ps aux --sort=-%mem | head -n 11", "Ver los 10 procesos con mayor uso de RAM/CPU"

    # Estado de git
    if re.search(r"\b(?:git\s+status|estado\s+de\s+git|haz\s+un\s+git\s+status)\b", low):
        return "git status -s && git branch --show-current", "Consultar estado del repositorio Git"

    return None


def plan_command_with_llm(user_text: str, llm_call_fn: Callable[[str], str]) -> tuple[str, str] | None:
    """Usa el LLM activo para traducir una petición en lenguaje natural a un comando Linux seguro."""
    folders_info = []
    for label in ("Descargas", "Documentos", "Escritorio", "Imágenes", "Música", "Vídeos"):
        p = os.path.join(HOME_DIR, label)
        if os.path.isdir(p):
            folders_info.append(p)

    prompt = (
        "Convierte la solicitud del usuario en UN ÚNICO comando de terminal Linux (bash) no interactivo.\n"
        f"- Directorio personal del usuario (HOME): {HOME_DIR}\n"
        f"- Carpetas existentes del usuario: {', '.join(folders_info) if folders_info else HOME_DIR}\n"
        f"- Directorio del proyecto Cloe: {PROJECT_DIR}\n"
        "- Reglas:\n"
        "  1. NO uses comandos interactivos (nano, vim, top sin -bn1, htop, less, man).\n"
        "  2. Si el usuario pide borrar el sistema o carpetas enteras críticas, escribe exactamente el comando que pidió para que el filtro de seguridad lo evalúe.\n"
        "  3. Responde ÚNICAMENTE con un objeto JSON válido con las claves \"command\" y \"explanation\", sin texto adicional ni bloques markdown.\n\n"
        f"Solicitud del usuario: {user_text}\n"
        "JSON:"
    )
    try:
        raw = llm_call_fn(prompt) or ""
        # Extraer primer bloque JSON
        m = re.search(r"\{.*?\}", raw, re.DOTALL)
        if not m:
            return None
        data = json.loads(m.group(0))
        cmd = str(data.get("command", "") or "").strip()
        exp = str(data.get("explanation", "") or "Ejecutar comando en terminal").strip()
        if cmd:
            return cmd, exp
    except Exception:
        pass
    return None


# ── Manejador Principal para el Loop de Chat ──────────────────────────────────

def handle_terminal_intent(
    user_text: str,
    llm_call_fn: Callable[[str], str] | None = None,
) -> str | None:
    """
    Gestiona tanto la confirmación/cancelación de comandos pendientes como
    nuevas solicitudes de terminal en Linux con política de seguridad de 3 niveles.
    """
    global _PENDING_COMMAND, _LAST_TERMINAL_CARD

    # 1. ¿El usuario está respondiendo a una solicitud de autorización pendiente?
    conf = is_terminal_confirmation_reply(user_text)
    if conf == "yes" and _PENDING_COMMAND is not None:
        pending = _PENDING_COMMAND
        _PENDING_COMMAND = None
        cmd = pending["command"]
        exp = pending["explanation"]
        res = execute_terminal_command(cmd)
        status_icon = "✅" if res["ok"] else "⚠️"
        _LAST_TERMINAL_CARD = {
            "kind": "terminal_result",
            "title": f"{status_icon} Terminal (Autorizado): {cmd[:48]}",
            "subtitle": res["output"][:140],
            "command": cmd,
        }
        return (
            f"[Sistema - Terminal Linux (AUTORIZADO POR EL USUARIO Y EJECUTADO)]:\n"
            f"- Comando ejecutado: `{cmd}` ({exp})\n"
            f"- Código de salida: {res['returncode']}\n"
            f"- Salida real de la terminal:\n```\n{res['output']}\n```\n"
            "Explica al usuario el resultado de forma breve y clara."
        )

    if conf == "no" and _PENDING_COMMAND is not None:
        cmd = _PENDING_COMMAND["command"]
        _PENDING_COMMAND = None
        _LAST_TERMINAL_CARD = {
            "kind": "terminal_result",
            "title": "🛑 Comando cancelado",
            "subtitle": f"No se ejecutó: {cmd}",
            "command": cmd,
        }
        return (
            f"[Sistema - Terminal Linux]: El usuario CANCELÓ la ejecución del comando `{cmd}`. "
            "Confírmale en 1 oración que no tocaste nada."
        )

    # 2. ¿Es una nueva solicitud para usar la terminal?
    if not is_terminal_request(user_text):
        return None

    planned = _fast_rule_translate(user_text)
    if planned is None and llm_call_fn is not None:
        planned = plan_command_with_llm(user_text, llm_call_fn)

    if planned is None:
        return None

    cmd, explanation = planned
    tier, safety_reason = classify_command_safety(cmd)

    # Nivel 1: PROHIBIDO (BLOCKED)
    if tier == "BLOCKED":
        _LAST_TERMINAL_CARD = {
            "kind": "terminal_result",
            "title": "🛡️ Comando Bloqueado por Seguridad",
            "subtitle": f"Bloqueado: {cmd[:60]} — {safety_reason}",
            "command": cmd,
        }
        return (
            f"[Sistema - Escudo de Seguridad de Terminal Linux]:\n"
            f"- Comando solicitado: `{cmd}`\n"
            f"- Estado: **BLOQUEADO PERMANENTEMENTE**\n"
            f"- Motivo de seguridad: {safety_reason}\n"
            "Dile al usuario con firmeza pero con cariño que tu protocolo de seguridad prohíbe ejecutar comandos destructivos o peligrosos para su sistema o sus carpetas personales."
        )

    # Nivel 2: REQUIERE AUTORIZACIÓN (CONFIRM)
    if tier == "CONFIRM":
        _PENDING_COMMAND = {
            "command": cmd,
            "explanation": explanation,
            "reason": safety_reason,
        }
        _LAST_TERMINAL_CARD = {
            "kind": "terminal_confirm",
            "title": f"⚠️ Requiere tu autorización: {cmd[:46]}",
            "subtitle": f"{safety_reason} Pulsa Autorizar o escribe 'autorizo'.",
            "command": cmd,
        }
        return (
            f"[Sistema - Autorización de Terminal Requerida]:\n"
            f"- Comando preparado (NO ejecutado aún): `{cmd}`\n"
            f"- Qué hace: {explanation}\n"
            f"- Por qué requiere permiso: {safety_reason}\n"
            "Pídele permiso explícito al usuario antes de ejecutarlo: muéstrale el comando entre backticks (`...`) y dile que puede pulsar el botón **✅ Autorizar** en la tarjeta o responder **\"autorizo\"** o **\"cancelar\"**."
        )

    # Nivel 3: SEGURO (SAFE) -> Ejecutar directamente
    res = execute_terminal_command(cmd)
    status_icon = "💻" if res["ok"] else "⚠️"
    _LAST_TERMINAL_CARD = {
        "kind": "terminal_result",
        "title": f"{status_icon} $ {cmd[:52]}",
        "subtitle": res["output"].splitlines()[0][:120] if res["output"] else "Listo",
        "command": cmd,
    }
    return (
        f"[Sistema - Terminal Linux (EJECUTADO CON SEGURIDAD)]:\n"
        f"- Comando ejecutado: `{cmd}` ({explanation})\n"
        f"- Código de salida: {res['returncode']}\n"
        f"- Salida real de la terminal:\n```\n{res['output']}\n```\n"
        "Responde al usuario con los datos reales obtenidos de la terminal. Si el usuario quiere ver el detalle, puedes incluir los datos clave de forma clara."
    )
