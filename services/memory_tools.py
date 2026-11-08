"""Módulo 1: Memoria Persistente de Usuario y Recordatorios / Pomodoro Michi."""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEMORY_FILE = os.path.join(_ROOT, "memory.json")


def load_memory() -> dict[str, Any]:
    """Carga la memoria persistente desde memory.json."""
    if not os.path.exists(MEMORY_FILE):
        return {"facts": [], "updated_at": 0}
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return {"facts": [], "updated_at": 0}
        if not isinstance(data.get("facts"), list):
            data["facts"] = []
        return data
    except Exception:
        return {"facts": [], "updated_at": 0}


def save_memory(data: dict[str, Any]) -> None:
    """Guarda la memoria persistente en memory.json."""
    data["updated_at"] = int(time.time())
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
    except Exception:
        pass


def add_memory_fact(fact: str) -> bool:
    """Añade un dato a la memoria persistente si no está duplicado."""
    cleaned = (fact or "").strip().strip(".,;:")
    if len(cleaned) < 3:
        return False
    data = load_memory()
    facts: list[str] = data.get("facts", [])
    lower_set = {f.lower() for f in facts}
    if cleaned.lower() in lower_set:
        return False
    facts.append(cleaned)
    if len(facts) > 40:
        facts = facts[-40:]
    data["facts"] = facts
    save_memory(data)
    return True


def remove_memory_fact(query: str) -> int:
    """Elimina recuerdos que coincidan con la consulta. Devuelve cuántos se borraron."""
    q = (query or "").strip().lower()
    if not q:
        return 0
    data = load_memory()
    facts: list[str] = data.get("facts", [])
    if q in ("todo", "todos", "toda la memoria", "todo lo que sabes"):
        removed = len(facts)
        data["facts"] = []
        save_memory(data)
        return removed
    kept = [f for f in facts if q not in f.lower()]
    removed = len(facts) - len(kept)
    if removed > 0:
        data["facts"] = kept
        save_memory(data)
    return removed


def format_memory_for_system() -> str:
    """Formatea los recuerdos guardados para inyectarlos en el system prompt de Cloe."""
    facts = load_memory().get("facts", [])
    if not facts:
        return ""
    lines = [
        "## MEMORIA PERSISTENTE DEL USUARIO (Datos reales que recuerdas de charlas pasadas):",
        "Usa estos datos de forma natural cuando tengan relación con la conversación:",
    ]
    for f in facts:
        lines.append(f"- {f}")
    return "\n".join(lines)


# ── Detección de Memoria en Lenguaje Natural ──────────────────────────────────

_REMEMBER_PATTERNS = [
    re.compile(r"^(?:cloe[,:\s]+)?(?:recuerda|acuérdate|acuerdate|guarda en tu memoria|anota)\s+(?:que\s+|de que\s+)?(.+)$", re.IGNORECASE),
    re.compile(r"^(?:cloe[,:\s]+)?(?:no olvides|ten en cuenta)\s+(?:que\s+)?(.+)$", re.IGNORECASE),
    re.compile(r"^(?:hola\s+cloe[,:\s]+)?(me llamo\s+[a-záéíóúñA-ZÁÉÍÓÚÑ0-9_ -]{2,35})$", re.IGNORECASE),
    re.compile(r"^(?:hola\s+cloe[,:\s]+)?(mi nombre es\s+[a-záéíóúñA-ZÁÉÍÓÚÑ0-9_ -]{2,35})$", re.IGNORECASE),
]

_FORGET_PATTERN = re.compile(
    r"^(?:cloe[,:\s]+)?(?:olvida|borra de tu memoria|elimina de tu memoria)\s+(?:que\s+|sobre\s+)?(.+)$",
    re.IGNORECASE,
)


def extract_and_store_user_memory(user_text: str) -> str | None:
    """
    Si el mensaje del usuario pide recordar u olvidar algo (y NO es un temporizador 'recuérdame en X min'),
    actualiza memory.json automáticamente y devuelve una nota de confirmación opcional.
    """
    txt = (user_text or "").strip()
    if not txt:
        return None

    # No confundir con un temporizador ("recuérdame en 10 minutos...")
    if parse_reminder_request(txt) is not None:
        return None

    m_forget = _FORGET_PATTERN.match(txt)
    if m_forget:
        target = m_forget.group(1).strip()
        count = remove_memory_fact(target)
        return f"[Memoria actualizada: se borraron {count} recuerdos relacionados con '{target}']"

    for pat in _REMEMBER_PATTERNS:
        m = pat.match(txt)
        if m:
            fact = m.group(1).strip()
            # Evitar guardar si es un recordatorio con tiempo ("en 5 minutos")
            if re.search(r"\ben\s+\d+\s*(?:seg|min|hor|h|m|s)\b", fact, re.IGNORECASE):
                return None
            if add_memory_fact(fact):
                return f"[Memoria guardada en memory.json: '{fact}']"
    return None


# ── Detección de Recordatorios / Temporizadores / Pomodoro ────────────────────

_REMINDER_REGEX = re.compile(
    r"(?:recuérdame|recuerdame|avísame|avisame|pon(?:me)?\s+un\s+(?:recordatorio|temporizador|timer|alarma))"
    r"(?:\s+en|\s+dentro\s+de)?\s+"
    r"(\d+)\s*(segundos?|segs?|s|minutos?|mins?|m|horas?|hrs?|h)\b"
    r"(?:\s*(?:para|de|que|:)?\s*(.*))?",
    re.IGNORECASE,
)

_REMINDER_ALT_REGEX = re.compile(
    r"\ben\s+(\d+)\s*(segundos?|segs?|s|minutos?|mins?|m|horas?|hrs?|h)\s+"
    r"(?:recuérdame|recuerdame|avísame|avisame)\s*(?:que|de|para)?\s*(.*)",
    re.IGNORECASE,
)

_POMODORO_REGEX = re.compile(
    r"\b(?:pon(?:me)?|inicia|empieza|activa|arranca)?\s*(?:un\s+)?pomodoro"
    r"(?:\s+de\s+(\d+)\s*(?:minutos?|mins?|m|segundos?|segs?|s)?)?"
    r"(?:\s+(?:para|de)\s+(.+))?",
    re.IGNORECASE,
)

_CANCEL_TIMER_REGEX = re.compile(
    r"\b(?:cancela|detén|deten|para|borra|quita)\s+(?:el\s+|los\s+|todos\s+los\s+)?"
    r"(?:recordatorios?|temporizador(?:es)?|timers?|pomodoros?|alarmas?)\b",
    re.IGNORECASE,
)


def parse_reminder_request(user_text: str) -> dict[str, Any] | None:
    """
    Detecta si el usuario pide un recordatorio, temporizador o Pomodoro:
    Retorna:
      - {"action": "cancel"} si pide cancelar temporizadores
      - {"action": "start", "seconds": int, "label": str, "kind": "reminder" | "pomodoro"}
      - None si no es una petición de temporizador/recordatorio.
    """
    txt = (user_text or "").strip()
    if not txt:
        return None

    if _CANCEL_TIMER_REGEX.search(txt):
        return {"action": "cancel"}

    # 1. ¿Pidió un Pomodoro?
    if "pomodoro" in txt.lower():
        m_pomo = _POMODORO_REGEX.search(txt)
        if m_pomo:
            raw_num = m_pomo.group(1)
            minutes = int(raw_num) if (raw_num and raw_num.isdigit()) else 25
            task = (m_pomo.group(2) or "Concentración Michi").strip().strip(".,!?")
            is_sec = bool(re.search(r"\d+\s*(?:segundos?|segs?|s)\b", txt, re.IGNORECASE))
            seconds = minutes if is_sec else minutes * 60
            return {
                "action": "start",
                "seconds": max(5, seconds),
                "label": f"🍅 Pomodoro: {task}",
                "kind": "pomodoro",
            }

    # 2. ¿Pidió un recordatorio / temporizador en X tiempo?
    m = _REMINDER_REGEX.search(txt) or _REMINDER_ALT_REGEX.search(txt)
    if m:
        amount = int(m.group(1))
        unit = m.group(2).lower()
        task = (m.group(3) or "¡Tiempo cumplido!").strip().strip(".,!?")
        if not task:
            task = "¡Tiempo cumplido!"
        if unit.startswith("h"):
            seconds = amount * 3600
        elif unit.startswith("m"):
            seconds = amount * 60
        else:
            seconds = amount
        return {
            "action": "start",
            "seconds": max(3, seconds),
            "label": task,
            "kind": "reminder",
        }

    return None
