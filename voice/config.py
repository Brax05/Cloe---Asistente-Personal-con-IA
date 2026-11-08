"""Configuración de la capa de voz de Cloe.

Todo se puede sobrescribir por variables de entorno para que el mismo código
funcione en la PC, en un servidor o, más adelante, con proveedores en la nube.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


VOICE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = VOICE_DIR.parent

try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env", override=True)
except ImportError:
    pass


def _env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return default if value is None else value.strip()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "si", "sí", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


def _path(value: str | os.PathLike[str] | None, default: Path) -> Path:
    if not value:
        return default
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    return candidate


@dataclass
class VoiceConfig:
    """Configuración completa de entrada y salida de voz."""

    # ── Reconocimiento de voz (STT) ────────────────────────────────────────
    stt_provider: str = "local"          # local | cloud (la nube se añade después)
    stt_model: str = "small"             # tiny | base | small | medium | large-v3
    stt_device: str = "auto"             # auto | cuda | cpu
    stt_compute_type: str = "auto"       # auto | float16 | int8 | float32
    stt_language: str = "es"
    stt_beam_size: int = 1
    stt_initial_prompt: str = (
        "Cloe, asistente personal con voz de gato. Conversación en español."
    )
    stt_download_root: Path = field(default_factory=lambda: VOICE_DIR / "models" / "whisper")

    # ── Síntesis de voz (TTS) ──────────────────────────────────────────────
    tts_provider: str = "local"          # local | cloud (la nube se añade después)
    tts_engine: str = "kokoro"           # auto | edge | kokoro | piper | espeak | none
    piper_bin: Path = field(default_factory=lambda: VOICE_DIR / "vendor" / "piper" / "piper")
    piper_model: Path = field(
        default_factory=lambda: VOICE_DIR / "models" / "piper" / "es_MX-claude-high.onnx"
    )
    piper_config: Path = field(
        default_factory=lambda: VOICE_DIR / "models" / "piper" / "es_MX-claude-high.onnx.json"
    )
    piper_espeak_data: Path = field(
        default_factory=lambda: VOICE_DIR / "vendor" / "piper" / "espeak-ng-data"
    )
    piper_length_scale: float = 0.98     # <1 = habla un poco más ágil y natural
    piper_noise_scale: float = 0.667
    piper_noise_w: float = 0.8
    # ── Kokoro (TTS neural local, más natural) ────────────────────────────────
    kokoro_model: Path = field(
        default_factory=lambda: VOICE_DIR / "models" / "kokoro" / "kokoro-v1.0.onnx"
    )
    kokoro_voices: Path = field(
        default_factory=lambda: VOICE_DIR / "models" / "kokoro" / "voices-v1.0.bin"
    )
    kokoro_voice: str = "ef_dora"       # ef_dora (femenina), em_alex (masculino)
    kokoro_speed: float = 1.08          # ligeramente más fluida para conversación
    kokoro_lang: str = "es"
    # ── Edge Neural TTS (voz humana expresiva en español) ────────────────────
    edge_voice: str = "es-MX-DaliaNeural"
    edge_rate: str = "+6%"
    edge_pitch: str = "+2Hz"
    max_speak_chars: int = 1500

    # ── Micrófono / altavoz ────────────────────────────────────────────────
    sample_rate: int = 16000
    frame_ms: int = 30
    silence_ms: int = 600                # silencio ágil que cierra el turno conversacional
    min_speech_ms: int = 240             # voz mínima para considerar que hablaste
    max_record_s: float = 30.0
    no_speech_timeout_s: float = 8.0     # si no hablas, se cancela la escucha
    speech_threshold: float = 0.010      # RMS normalizado mínimo (0-1)
    noise_calibration_ms: int = 300      # calibración rápida del ruido ambiente
    noise_multiplier: float = 2.3        # umbral = ruido × este factor al empezar
    noise_sustain_multiplier: float = 1.6  # umbral para seguir hablando
    start_consecutive_frames: int = 3    # frames seguidos sobre el umbral para arrancar
    peak_ratio: float = 1.5              # pico mínimo vs umbral para validar voz
    max_speech_threshold: float = 0.080  # tope del umbral si la calibración oye voz
    input_target: str = ""               # nombre/serial de fuente PipeWire o device ALSA
    output_target: str = ""              # nombre/serial de sink PipeWire o device ALSA

    # ── Comportamiento ─────────────────────────────────────────────────────
    speak_solo: bool = False             # ¿leer también los mensajes espontáneos?
    clean_text: bool = True              # quitar kaomojis/markdown antes de hablar

    @classmethod
    def from_env(cls) -> "VoiceConfig":
        """Construye la configuración leyendo variables CLOE_* del entorno."""
        cfg = cls()
        cfg.stt_provider = _env("CLOE_STT_PROVIDER", cfg.stt_provider).lower()
        cfg.stt_model = _env("CLOE_STT_MODEL", cfg.stt_model)
        cfg.stt_device = _env("CLOE_STT_DEVICE", cfg.stt_device).lower()
        cfg.stt_compute_type = _env("CLOE_STT_COMPUTE_TYPE", cfg.stt_compute_type).lower()
        cfg.stt_language = _env("CLOE_STT_LANGUAGE", cfg.stt_language)
        cfg.stt_beam_size = _env_int("CLOE_STT_BEAM_SIZE", cfg.stt_beam_size)
        cfg.stt_initial_prompt = _env("CLOE_STT_PROMPT", cfg.stt_initial_prompt)
        cfg.stt_download_root = _path(
            _env("CLOE_STT_DOWNLOAD_ROOT"), cfg.stt_download_root
        )

        cfg.tts_provider = _env("CLOE_TTS_PROVIDER", cfg.tts_provider).lower()
        cfg.tts_engine = _env("CLOE_TTS_ENGINE", cfg.tts_engine).lower()
        cfg.piper_bin = _path(_env("CLOE_PIPER_BIN"), cfg.piper_bin)
        piper_model_env = _env("CLOE_PIPER_MODEL")
        piper_config_env = _env("CLOE_PIPER_CONFIG")
        cfg.piper_model = _path(piper_model_env, cfg.piper_model)
        cfg.piper_config = _path(piper_config_env, cfg.piper_config)
        voice_name = _env("CLOE_PIPER_VOICE")
        if voice_name:
            base = cfg.piper_model.parent / f"{voice_name}.onnx"
            if not piper_model_env:
                cfg.piper_model = base
            if not piper_config_env:
                cfg.piper_config = cfg.piper_model.with_name(
                    cfg.piper_model.name + ".json"
                )
        cfg.piper_espeak_data = _path(
            _env("CLOE_PIPER_ESPEAK_DATA"), cfg.piper_espeak_data
        )
        cfg.piper_length_scale = _env_float(
            "CLOE_PIPER_LENGTH_SCALE", cfg.piper_length_scale
        )
        cfg.piper_noise_scale = _env_float(
            "CLOE_PIPER_NOISE_SCALE", cfg.piper_noise_scale
        )
        cfg.piper_noise_w = _env_float("CLOE_PIPER_NOISE_W", cfg.piper_noise_w)
        cfg.kokoro_model = _path(
            _env("CLOE_KOKORO_MODEL"), cfg.kokoro_model
        )
        cfg.kokoro_voices = _path(
            _env("CLOE_KOKORO_VOICES"), cfg.kokoro_voices
        )
        cfg.kokoro_voice = _env("CLOE_KOKORO_VOICE", cfg.kokoro_voice)
        cfg.kokoro_speed = _env_float("CLOE_KOKORO_SPEED", cfg.kokoro_speed)
        cfg.kokoro_lang = _env("CLOE_KOKORO_LANG", cfg.kokoro_lang)
        cfg.edge_voice = _env("CLOE_EDGE_VOICE", cfg.edge_voice)
        cfg.edge_rate = _env("CLOE_EDGE_RATE", cfg.edge_rate)
        cfg.edge_pitch = _env("CLOE_EDGE_PITCH", cfg.edge_pitch)
        cfg.max_speak_chars = _env_int("CLOE_MAX_SPEAK_CHARS", cfg.max_speak_chars)

        cfg.sample_rate = _env_int("CLOE_SAMPLE_RATE", cfg.sample_rate)
        cfg.frame_ms = _env_int("CLOE_FRAME_MS", cfg.frame_ms)
        cfg.silence_ms = _env_int("CLOE_VOICE_SILENCE_MS", cfg.silence_ms)
        cfg.min_speech_ms = _env_int("CLOE_VOICE_MIN_SPEECH_MS", cfg.min_speech_ms)
        cfg.max_record_s = _env_float("CLOE_VOICE_MAX_RECORD_S", cfg.max_record_s)
        cfg.no_speech_timeout_s = _env_float(
            "CLOE_VOICE_NO_SPEECH_TIMEOUT_S", cfg.no_speech_timeout_s
        )
        cfg.speech_threshold = _env_float(
            "CLOE_VOICE_THRESHOLD", cfg.speech_threshold
        )
        cfg.noise_calibration_ms = _env_int(
            "CLOE_VOICE_CALIBRATION_MS", cfg.noise_calibration_ms
        )
        cfg.noise_multiplier = _env_float(
            "CLOE_VOICE_NOISE_MULT", cfg.noise_multiplier
        )
        cfg.noise_sustain_multiplier = _env_float(
            "CLOE_VOICE_NOISE_SUSTAIN", cfg.noise_sustain_multiplier
        )
        cfg.start_consecutive_frames = _env_int(
            "CLOE_VOICE_START_FRAMES", cfg.start_consecutive_frames
        )
        cfg.peak_ratio = _env_float(
            "CLOE_VOICE_PEAK_RATIO", cfg.peak_ratio
        )
        cfg.max_speech_threshold = _env_float(
            "CLOE_VOICE_MAX_THRESHOLD", cfg.max_speech_threshold
        )
        cfg.input_target = _env("CLOE_MIC_TARGET", cfg.input_target)
        cfg.output_target = _env("CLOE_SPEAKER_TARGET", cfg.output_target)
        cfg.speak_solo = _env_bool("CLOE_SPEAK_SOLO", cfg.speak_solo)
        cfg.clean_text = _env_bool("CLOE_CLEAN_TEXT", cfg.clean_text)

        return cfg

    def validate(self) -> list[str]:
        """Devuelve una lista de problemas legibles; vacía si todo está bien."""
        problems: list[str] = []
        if self.stt_provider == "local":
            if self.stt_device not in {"auto", "cuda", "cpu"}:
                problems.append(f"CLOE_STT_DEVICE inválido: {self.stt_device}")
            if self.stt_compute_type not in {"auto", "float16", "int8", "float32"}:
                problems.append(
                    f"CLOE_STT_COMPUTE_TYPE inválido: {self.stt_compute_type}"
                )
        else:
            problems.append(
                f"Proveedor STT '{self.stt_provider}' aún no implementado "
                "(la interfaz está lista para añadirlo)."
            )

        if self.tts_provider != "local":
            problems.append(
                f"Proveedor TTS '{self.tts_provider}' aún no implementado "
                "(la interfaz está lista para añadirlo)."
            )
        elif self.tts_engine == "piper":
            for label, path in (
                ("CLOE_PIPER_BIN", self.piper_bin),
                ("CLOE_PIPER_MODEL", self.piper_model),
                ("CLOE_PIPER_CONFIG", self.piper_config),
            ):
                if not path.exists():
                    problems.append(f"Falta {label}: {path}")
        elif self.tts_engine == "kokoro":
            for label, path in (
                ("CLOE_KOKORO_MODEL", self.kokoro_model),
                ("CLOE_KOKORO_VOICES", self.kokoro_voices),
            ):
                if not path.exists():
                    problems.append(f"Falta {label}: {path}")
        return problems
