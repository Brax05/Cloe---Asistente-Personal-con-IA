"""Capa de voz de Cloe.

Diseño en capas:
    config  → qué motor y qué parámetros usar
    audio   → micrófono y altavoz del sistema
    stt     → audio a texto (hoy local, mañana nube)
    tts     → texto a audio (hoy local, mañana nube)
    text    → limpieza de kaomojis/markdown antes de hablar
    io      → VoiceIO, la fachada que consumen terminal y GUI
    calls   → CallBridge, la interfaz para llamadas reales
"""

from .config import VoiceConfig
from .io import SpeechStream, VoiceError, VoiceIO
from .stt import FasterWhisperSTT, STTEngine, STTError, create_stt
from .text import clean_for_speech, pop_streaming_sentence, split_for_speech, truncate_for_speech
from .tts import EdgeTTS, EspeakTTS, KokoroTTS, PiperTTS, TTSEngine, TTSError, create_tts

_CALL_EXPORTS = {
    "CallBridge",
    "CallConfig",
    "CallError",
    "CallSession",
    "CallState",
    "UnavailableCallBridge",
    "create_call_bridge",
    "normalize_phone_number",
    "register_call_provider",
}


def __getattr__(name: str):
    """Importa la capa de llamadas solo cuando se usa.

    Así ``python -m voice.calls`` no vuelve a ejecutar el módulo durante la
    importación del paquete.
    """
    if name in _CALL_EXPORTS:
        import importlib

        module = importlib.import_module(".calls", __name__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "VoiceConfig",
    "VoiceIO",
    "VoiceError",
    "SpeechStream",
    "CallBridge",
    "CallConfig",
    "CallError",
    "CallSession",
    "CallState",
    "UnavailableCallBridge",
    "create_call_bridge",
    "normalize_phone_number",
    "register_call_provider",
    "STTEngine",
    "STTError",
    "FasterWhisperSTT",
    "create_stt",
    "TTSEngine",
    "TTSError",
    "PiperTTS",
    "EspeakTTS",
    "KokoroTTS",
    "EdgeTTS",
    "create_tts",
    "clean_for_speech",
    "truncate_for_speech",
    "split_for_speech",
    "pop_streaming_sentence",
]

