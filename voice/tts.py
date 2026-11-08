"""Síntesis de voz (TTS) local y neural, con pipeline de baja latencia por frases."""

from __future__ import annotations

import asyncio
import io
import logging
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import wave
from abc import ABC, abstractmethod
from pathlib import Path

import numpy as np

try:
    from kokoro_onnx import Kokoro as _Kokoro

    KOKORO_AVAILABLE = True
except ImportError:  # pragma: no cover - dependencia opcional
    _Kokoro = None
    KOKORO_AVAILABLE = False

try:
    import edge_tts as _edge_tts

    EDGE_TTS_AVAILABLE = True
except ImportError:  # pragma: no cover - dependencia opcional
    _edge_tts = None
    EDGE_TTS_AVAILABLE = False

from .audio import AudioError, WavPlayer
from .config import VoiceConfig
from .text import clean_for_speech, split_for_speech, truncate_for_speech

log = logging.getLogger("cloe.voice")


class TTSError(RuntimeError):
    """Fallo al sintetizar o reproducir voz."""


class TTSEngine(ABC):
    """Contrato mínimo para cualquier motor de voz con soporte de streaming por frases."""

    name = "base"
    audio_suffix = ".wav"

    def __init__(self, config: VoiceConfig | None = None):
        self.config = config or VoiceConfig()
        self.player = WavPlayer(self.config)
        self._stop_event = threading.Event()
        self._synth_lock = threading.Lock()

    @abstractmethod
    def synthesize(self, text: str) -> bytes:
        """Devuelve audio en memoria con la voz sintetizada."""

    def speak(self, text: str) -> None:
        """Divide en frases, pre-sintetiza en paralelo y reproduce sin pausas."""
        if not text or not text.strip():
            return
        self._stop_event.clear()
        sentences = split_for_speech(text)
        if not sentences:
            return
        if len(sentences) == 1:
            with self._synth_lock:
                if self._stop_event.is_set():
                    return
                audio = self.synthesize(sentences[0])
            if audio and not self._stop_event.is_set():
                self.player.play_bytes(audio, suffix=self.audio_suffix)
            return

        audio_q: queue.Queue[bytes | None] = queue.Queue(maxsize=2)

        def producer() -> None:
            try:
                for sentence in sentences:
                    if self._stop_event.is_set():
                        break
                    with self._synth_lock:
                        if self._stop_event.is_set():
                            break
                        data = self.synthesize(sentence)
                    if data and not self._stop_event.is_set():
                        audio_q.put(data)
            except Exception as exc:
                log.warning("Error sintetizando frase en pipeline: %s", exc)
            finally:
                audio_q.put(None)

        prod_thread = threading.Thread(target=producer, daemon=True)
        prod_thread.start()

        while not self._stop_event.is_set():
            item = audio_q.get()
            if item is None:
                break
            if not self._stop_event.is_set():
                self.player.play_bytes(item, suffix=self.audio_suffix)

    def stop(self) -> None:
        """Interrumpe la reproducción y síntesis en curso inmediatamente."""
        self._stop_event.set()
        self.player.stop()

    def close(self) -> None:
        """Libera recursos."""
        self.stop()


class PiperTTS(TTSEngine):
    """Piper local: rápida, privada y con voces en español de México."""

    name = "piper"

    def __init__(self, config: VoiceConfig):
        super().__init__(config)
        self._validate()

    def _validate(self) -> None:
        cfg = self.config
        if not cfg.piper_bin.exists():
            raise TTSError(
                f"No encontré el binario de Piper en {cfg.piper_bin}.\n"
                "Ejecuta: python -m voice.setup_models"
            )
        if not os.access(cfg.piper_bin, os.X_OK):
            raise TTSError(f"Piper no es ejecutable: {cfg.piper_bin}")
        if not cfg.piper_model.exists():
            raise TTSError(
                f"No encontré la voz de Piper en {cfg.piper_model}.\n"
                "Ejecuta: python -m voice.setup_models"
            )
        if not cfg.piper_config.exists():
            raise TTSError(f"No encontré la configuración de la voz: {cfg.piper_config}")

    def _prepare_text(self, text: str) -> str:
        prepared = clean_for_speech(text) if self.config.clean_text else text
        return truncate_for_speech(prepared, self.config.max_speak_chars)

    def _command(self) -> list[str]:
        cfg = self.config
        cmd = [
            str(cfg.piper_bin),
            "--model", str(cfg.piper_model),
            "--config", str(cfg.piper_config),
            "--output_file", "-",
            "--length_scale", str(cfg.piper_length_scale),
            "--noise_scale", str(cfg.piper_noise_scale),
            "--noise_w", str(cfg.piper_noise_w),
            "--sentence_silence", "0.15",
            "--quiet",
        ]
        if cfg.piper_espeak_data.exists():
            cmd += ["--espeak_data", str(cfg.piper_espeak_data)]
        return cmd

    def _environment(self) -> dict[str, str]:
        env = os.environ.copy()
        lib_dir = str(self.config.piper_bin.parent)
        current = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = lib_dir if not current else f"{lib_dir}:{current}"
        return env

    def synthesize(self, text: str) -> bytes:
        prepared = self._prepare_text(text)
        if not prepared:
            return b""
        try:
            result = subprocess.run(
                self._command(),
                input=prepared.encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=120,
                env=self._environment(),
                cwd=str(self.config.piper_bin.parent),
            )
        except FileNotFoundError as exc:
            raise TTSError(f"No pude ejecutar Piper: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise TTSError("Piper tardó demasiado en sintetizar la respuesta.") from exc

        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise TTSError(f"Piper falló ({result.returncode}): {detail}")
        if not result.stdout:
            raise TTSError("Piper devolvió audio vacío.")
        return result.stdout


class EspeakTTS(TTSEngine):
    """Respaldo ligero si Piper no está disponible (voz más robótica)."""

    name = "espeak"

    def __init__(self, config: VoiceConfig):
        super().__init__(config)
        self.binary = shutil.which("espeak-ng") or shutil.which("espeak")
        if not self.binary:
            raise TTSError(
                "No encontré espeak-ng ni espeak. Instala espeak-ng o usa Piper."
            )

    def _prepare_text(self, text: str) -> str:
        prepared = clean_for_speech(text) if self.config.clean_text else text
        return truncate_for_speech(prepared, self.config.max_speak_chars)

    def synthesize(self, text: str) -> bytes:
        prepared = self._prepare_text(text)
        if not prepared:
            return b""
        fd, path = tempfile.mkstemp(prefix="cloe_espeak_", suffix=".wav")
        os.close(fd)
        try:
            result = subprocess.run(
                [
                    self.binary,
                    "-v", "es",
                    "-s", "165",
                    "-w", path,
                    prepared,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=60,
            )
            if result.returncode != 0:
                detail = result.stderr.decode("utf-8", errors="replace").strip()
                raise TTSError(f"espeak falló ({result.returncode}): {detail}")
            return Path(path).read_bytes()
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass


class KokoroTTS(TTSEngine):
    """TTS neural local con Kokoro (ONNX). Voz mucho más natural que Piper.

    Requiere `kokoro-onnx` y los archivos `kokoro-v1.0.onnx` + `voices-v1.0.bin`
    en `voice/models/kokoro/` (descargables con `voice.setup_models --kokoro`).
    """

    name = "kokoro"

    def __init__(self, config: VoiceConfig):
        if not KOKORO_AVAILABLE:
            raise TTSError(
                "Falta la dependencia 'kokoro-onnx'. "
                "Instálala con: pip install kokoro-onnx"
            )
        super().__init__(config)
        model_path = config.kokoro_model
        voices_path = config.kokoro_voices
        if not model_path.exists() or not voices_path.exists():
            raise TTSError(
                "No encontré los archivos de Kokoro.\n"
                "Ejecuta: python -m voice.setup_models --kokoro\n"
                f"  modelo:  {model_path}\n"
                f"  voces:   {voices_path}"
            )
        try:
            self._kokoro = _Kokoro(str(model_path), str(voices_path))
        except Exception as exc:
            raise TTSError(f"No pude cargar Kokoro: {exc}") from exc

        if config.kokoro_voice not in self._kokoro.voices:
            raise TTSError(
                f"Voz Kokoro desconocida: {config.kokoro_voice}. "
                f"Disponibles: {', '.join(sorted(self._kokoro.voices))}"
            )

    def _prepare_text(self, text: str) -> str:
        prepared = clean_for_speech(text) if self.config.clean_text else text
        return truncate_for_speech(prepared, self.config.max_speak_chars)

    def synthesize(self, text: str) -> bytes:
        prepared = self._prepare_text(text)
        if not prepared:
            return b""
        try:
            samples, sample_rate = self._kokoro.create(
                prepared,
                voice=self.config.kokoro_voice,
                speed=self.config.kokoro_speed,
                lang=self.config.kokoro_lang,
            )
        except Exception as exc:
            raise TTSError(f"Kokoro falló al sintetizar: {exc}") from exc

        if samples is None or len(samples) == 0:
            return b""

        pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype(np.int16)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(int(sample_rate))
            wav_file.writeframes(pcm.tobytes())
        return buf.getvalue()


class EdgeTTS(TTSEngine):
    """Voz neural hiper-natural en español (Microsoft Edge Neural TTS).

    Si no hay conexión o falta `edge-tts`, cae automáticamente a Kokoro o Piper.
    """

    name = "edge"
    audio_suffix = ".mp3"

    def __init__(self, config: VoiceConfig, fallback: TTSEngine | None = None):
        if not EDGE_TTS_AVAILABLE:
            raise TTSError(
                "Falta 'edge-tts'. Instálalo con: pip install edge-tts"
            )
        super().__init__(config)
        self._fallback = fallback

    def _prepare_text(self, text: str) -> str:
        prepared = clean_for_speech(text) if self.config.clean_text else text
        return truncate_for_speech(prepared, self.config.max_speak_chars)

    async def _synthesize_async(self, text: str) -> bytes:
        communicate = _edge_tts.Communicate(
            text,
            voice=self.config.edge_voice,
            rate=self.config.edge_rate,
            pitch=self.config.edge_pitch,
        )
        chunks: list[bytes] = []
        async for chunk in communicate.stream():
            if self._stop_event.is_set():
                return b""
            if chunk.get("type") == "audio" and chunk.get("data"):
                chunks.append(chunk["data"])
        return b"".join(chunks)

    def synthesize(self, text: str) -> bytes:
        prepared = self._prepare_text(text)
        if not prepared:
            return b""
        try:
            return asyncio.run(self._synthesize_async(prepared))
        except Exception as exc:
            if self._fallback is not None:
                log.warning("EdgeTTS falló (%s), usando respaldo local.", exc)
                self.audio_suffix = self._fallback.audio_suffix
                return self._fallback.synthesize(text)
            raise TTSError(f"EdgeTTS falló al sintetizar: {exc}") from exc


class NullTTS(TTSEngine):
    """Silencio: útil para pruebas o para desactivar la voz sin romper nada."""

    name = "none"

    def synthesize(self, text: str) -> bytes:
        return b""

    def speak(self, text: str) -> None:
        return None


class CloudTTS(TTSEngine):
    """Punto de extensión para TTS en la nube."""

    def __init__(self, provider: str):
        raise TTSError(
            f"El proveedor TTS '{provider}' todavía no está implementado. "
            "La interfaz TTSEngine está lista para añadirlo sin tocar a Cloe."
        )

    def synthesize(self, text: str) -> bytes:
        return b""


def _build_local_fallback(config: VoiceConfig) -> TTSEngine | None:
    for cls in (KokoroTTS, PiperTTS, EspeakTTS):
        try:
            return cls(config)
        except Exception:
            continue
    return None


def create_tts(config: VoiceConfig) -> TTSEngine:
    if config.tts_provider == "cloud":
        return CloudTTS(config.tts_provider)
    if config.tts_provider != "local":
        raise TTSError(f"Proveedor TTS desconocido: {config.tts_provider}")

    engine = config.tts_engine.lower()
    if engine in {"none", "nulo", "off"}:
        return NullTTS()
    if engine == "edge":
        fallback = _build_local_fallback(config)
        try:
            return EdgeTTS(config, fallback=fallback)
        except TTSError:
            if fallback is not None:
                return fallback
            raise
    if engine == "auto":
        if EDGE_TTS_AVAILABLE:
            try:
                return EdgeTTS(config, fallback=_build_local_fallback(config))
            except Exception:
                pass
        fallback = _build_local_fallback(config)
        if fallback is not None:
            return fallback
        return NullTTS()
    if engine == "kokoro":
        try:
            return KokoroTTS(config)
        except TTSError:
            if config.piper_bin.exists() and config.piper_model.exists():
                log.warning("Kokoro no disponible, usando Piper como respaldo.")
                return PiperTTS(config)
            raise
    if engine == "piper":
        return PiperTTS(config)
    if engine in {"espeak", "espeak-ng"}:
        return EspeakTTS(config)
    raise TTSError(f"Motor TTS desconocido: {config.tts_engine}")

