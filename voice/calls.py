"""Capa de llamadas telefónicas de Cloe.

La voz y la llamada son capas separadas:

    VoiceIO     → micrófono y altavoz locales (hablar con el usuario)
    CallBridge  → transporte de la llamada (SIP, WebRTC, Android…)

Un proveedor concreto implementa ``CallBridge``. El resto de Cloe solo usa
``start_call``/``end_call``/``status``/``send_audio``/``read_audio``, sin saber
si la llamada va por internet, por un teléfono en altavoz o por un Android
rooteado.

Formato de audio del puente: PCM 16 bits little-endian, mono, 16 kHz.
"""

from __future__ import annotations

import os
import re
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class CallError(RuntimeError):
    """Fallo al iniciar, mantener o cerrar una llamada."""


class CallState(str, Enum):
    """Estados por los que pasa una llamada."""

    IDLE = "idle"
    DIALING = "dialing"
    RINGING = "ringing"
    ACTIVE = "active"
    ENDED = "ended"
    FAILED = "failed"


ACTIVE_STATES = (CallState.DIALING, CallState.RINGING, CallState.ACTIVE)

_PHONE_RE = re.compile(r"^\+?[1-9]\d{6,14}$")


def normalize_phone_number(raw: str) -> str:
    """Normaliza un número a formato internacional aproximado (E.164).

    Acepta espacios, guiones, puntos y paréntesis. El prefijo ``00`` se
    convierte en ``+``. No valida el país: eso lo hará el proveedor.
    """
    number = re.sub(r"[\s\-().]", "", str(raw or ""))
    if number.startswith("00"):
        number = "+" + number[2:]
    if not _PHONE_RE.match(number):
        raise CallError(
            "Número inválido. Usa formato internacional, por ejemplo "
            "+5215512345678."
        )
    return number


@dataclass
class CallSession:
    """Una llamada concreta y su estado actual."""

    call_id: str
    number: str
    objective: str = ""
    state: CallState = CallState.DIALING
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None
    detail: str = ""
    sample_rate: int = 16000

    @property
    def duration_s(self) -> float:
        end = self.ended_at if self.ended_at is not None else time.time()
        return max(0.0, end - self.started_at)

    def as_dict(self) -> dict:
        """Representación lista para el dispatcher de herramientas."""
        return {
            "call_id": self.call_id,
            "numero": self.number,
            "objetivo": self.objective,
            "estado": self.state.value,
            "duracion_s": round(self.duration_s, 1),
            "detalle": self.detail,
            "sample_rate": self.sample_rate,
        }


@dataclass
class CallConfig:
    """Configuración de la capa de llamadas (variables ``CLOE_CALL_*``)."""

    provider: str = "none"
    max_duration_s: float = 300.0
    allowlist: tuple[str, ...] = ()

    @classmethod
    def from_env(cls) -> "CallConfig":
        raw_allowlist = os.getenv("CLOE_CALL_ALLOWLIST", "")
        allowlist = tuple(
            part.strip() for part in raw_allowlist.split(",") if part.strip()
        )
        try:
            max_duration = float(os.getenv("CLOE_CALL_MAX_DURATION_S", "300"))
        except ValueError:
            max_duration = 300.0
        return cls(
            provider=os.getenv("CLOE_CALL_PROVIDER", "none").strip().lower(),
            max_duration_s=max(10.0, max_duration),
            allowlist=allowlist,
        )

    def validate_number(self, number: str) -> str:
        """Normaliza el número y aplica la lista blanca, si existe."""
        normalized = normalize_phone_number(number)
        if not self.allowlist:
            return normalized

        allowed: set[str] = set()
        for item in self.allowlist:
            try:
                allowed.add(normalize_phone_number(item))
            except CallError:
                continue
        if not allowed:
            raise CallError(
                "CLOE_CALL_ALLOWLIST no contiene números válidos. "
                "Corrige la lista o déjala vacía."
            )
        if normalized not in allowed:
            raise CallError(
                "Número fuera de la lista permitida (CLOE_CALL_ALLOWLIST)."
            )
        return normalized


class CallBridge(ABC):
    """Contrato mínimo de un transporte de llamadas.

    Un proveedor real (SIP, WebRTC, Android) hereda de esta clase e implementa
    ``start_call`` y ``end_call``. Para audio en tiempo real puede implementar
    ``send_audio`` y ``read_audio``; si no, Cloe seguirá funcionando con el
    puente acústico o con llamadas de solo voz sintetizada.
    """

    name = "base"
    provider = "base"

    def __init__(self, config: CallConfig | None = None):
        self.config = config or CallConfig.from_env()
        self._sessions: dict[str, CallSession] = {}

    @property
    def available(self) -> bool:
        """True si el proveedor está listo para hacer llamadas reales."""
        return False

    @property
    def reason(self) -> str:
        """Motivo por el que no está disponible (vacío si está listo)."""
        return ""

    @abstractmethod
    def start_call(self, number: str, objective: str = "") -> CallSession:
        """Marca el número y devuelve la sesión de llamada."""

    @abstractmethod
    def end_call(self, call_id: str | None = None) -> None:
        """Cuelga la llamada indicada o la llamada activa."""

    def status(self, call_id: str | None = None) -> CallSession | None:
        """Devuelve una sesión concreta o la llamada activa más reciente."""
        if call_id is not None:
            return self._sessions.get(call_id)
        for session in reversed(list(self._sessions.values())):
            if session.state in ACTIVE_STATES:
                return session
        return None

    def send_audio(
        self, call_id: str, pcm: bytes, sample_rate: int = 16000
    ) -> None:
        """Inyecta audio local (PCM 16-bit LE mono) en la llamada."""
        raise NotImplementedError("Este puente no permite inyectar audio.")

    def read_audio(self, call_id: str, timeout_s: float = 0.0) -> bytes:
        """Devuelve audio del otro lado (PCM 16-bit LE mono)."""
        raise NotImplementedError("Este puente no permite leer audio.")

    def close(self) -> None:
        """Cuelga las llamadas activas y libera recursos."""
        for session in list(self._sessions.values()):
            if session.state in ACTIVE_STATES:
                try:
                    self.end_call(session.call_id)
                except Exception:
                    pass

    # ── Utilidades para las implementaciones ───────────────────────────────
    def new_session(self, number: str, objective: str = "") -> CallSession:
        """Valida el número, crea la sesión y la registra."""
        normalized = self.config.validate_number(number)
        session = CallSession(
            call_id=uuid.uuid4().hex,
            number=normalized,
            objective=objective.strip(),
        )
        self._sessions[session.call_id] = session
        return session

    def finish_session(
        self,
        call_id: str,
        state: CallState = CallState.ENDED,
        detail: str = "",
    ) -> None:
        """Marca una sesión como terminada o fallida."""
        session = self._sessions.get(call_id)
        if session is None:
            return
        session.state = state
        session.ended_at = time.time()
        if detail:
            session.detail = detail


class UnavailableCallBridge(CallBridge):
    """Puente inerte que explica por qué las llamadas no están listas."""

    name = "sin proveedor"
    provider = "none"

    def __init__(self, config: CallConfig | None = None, reason: str = ""):
        super().__init__(config)
        self._reason = reason or (
            "Las llamadas no están configuradas. Define CLOE_CALL_PROVIDER "
            "con un proveedor implementado."
        )

    @property
    def reason(self) -> str:
        return self._reason

    def start_call(self, number: str, objective: str = "") -> CallSession:
        raise CallError(self._reason)

    def end_call(self, call_id: str | None = None) -> None:
        return None


CallBridgeFactory = Callable[[CallConfig], CallBridge]

_PROVIDERS: dict[str, CallBridgeFactory] = {}


def register_call_provider(name: str, factory: CallBridgeFactory) -> None:
    """Registra un proveedor de llamadas.

    Un plugin o un módulo opcional puede llamar a esta función al importarse::

        register_call_provider("sip", lambda cfg: SipBridge(cfg))
    """
    _PROVIDERS[name.strip().lower()] = factory


def available_providers() -> list[str]:
    """Nombres de proveedores registrados en este proceso."""
    return sorted(_PROVIDERS)


def create_call_bridge(config: CallConfig | None = None) -> CallBridge:
    """Construye el puente configurado en ``CLOE_CALL_PROVIDER``.

    Nunca falla por un proveedor ausente: devuelve un
    :class:`UnavailableCallBridge` con un motivo legible.
    """
    config = config or CallConfig.from_env()
    provider = config.provider
    if provider in ("", "none", "off", "0", "false"):
        return UnavailableCallBridge(
            config,
            "Las llamadas están desactivadas. Define CLOE_CALL_PROVIDER "
            "para habilitarlas.",
        )

    factory = _PROVIDERS.get(provider)
    if factory is None:
        registered = ", ".join(available_providers()) or "ninguno"
        return UnavailableCallBridge(
            config,
            f"El proveedor de llamadas '{provider}' aún no está implementado. "
            f"Proveedores registrados: {registered}.",
        )
    return factory(config)


def _main() -> int:
    """Diagnóstico rápido: ``python -m voice.calls``."""
    config = CallConfig.from_env()
    bridge = create_call_bridge(config)
    print("Estado de las llamadas de Cloe:")
    print(f"  · Proveedor configurado: {config.provider}")
    print(f"  · Estado: {'listo' if bridge.available else 'no disponible'}")
    if not bridge.available:
        print(f"  · Motivo: {bridge.reason}")
    print(f"  · Duración máxima: {config.max_duration_s:.0f} s")
    if config.allowlist:
        print(f"  · Números permitidos: {', '.join(config.allowlist)}")
    else:
        print("  · Números permitidos: todos (sin CLOE_CALL_ALLOWLIST)")
    print(
        "  · Proveedores registrados: "
        + (", ".join(available_providers()) or "ninguno")
    )
    bridge.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
