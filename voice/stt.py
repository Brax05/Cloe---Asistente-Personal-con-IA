"""Reconocimiento de voz (STT) con una interfaz lista para la nube."""

from __future__ import annotations

import logging
import os
import threading
from abc import ABC, abstractmethod

import numpy as np

from .audio import resample_linear
from .config import VoiceConfig

log = logging.getLogger("cloe.voice")


class STTError(RuntimeError):
    """Fallo al cargar o ejecutar el reconocimiento de voz."""


class STTEngine(ABC):
    """Contrato mínimo para cualquier motor de transcripción."""

    name = "base"

    @abstractmethod
    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        """Convierte audio float32 mono en texto."""

    def warmup(self) -> None:
        """Carga perezosa opcional antes de la primera transcripción."""

    def close(self) -> None:
        """Libera recursos."""


class FasterWhisperSTT(STTEngine):
    """Whisper local vía faster-whisper (CTranslate2)."""

    name = "faster-whisper"

    def __init__(self, config: VoiceConfig):
        self.config = config
        self._model = None
        self._lock = threading.Lock()
        self._device = ""
        self._compute_type = ""

    def _build(self, device: str, compute_type: str):
        from faster_whisper import WhisperModel

        cfg = self.config
        return WhisperModel(
            cfg.stt_model,
            device=device,
            compute_type=compute_type,
            download_root=str(cfg.stt_download_root),
            cpu_threads=max(1, (os.cpu_count() or 4) // 2),
            num_workers=1,
        )

    @staticmethod
    def _self_test(model) -> None:
        """Fuerza un encode real: cargar CUDA no garantiza que cublas exista."""
        dummy = np.zeros(8000, dtype=np.float32)
        segments, _ = model.transcribe(
            dummy, language="es", beam_size=1, vad_filter=False,
            without_timestamps=True,
        )
        for _segment in segments:
            pass

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel  # noqa: F401
        except ImportError as exc:  # pragma: no cover - depende del entorno
            raise STTError(
                "Falta faster-whisper. Instala las dependencias de voz con:\n"
                "  pip install -r requirements-voice.txt"
            ) from exc

        cfg = self.config
        cfg.stt_download_root.mkdir(parents=True, exist_ok=True)
        errors: list[str] = []

        candidates: list[tuple[str, str]] = []
        if cfg.stt_device == "auto":
            candidates = [("cuda", "float16"), ("cpu", "int8")]
        elif cfg.stt_device == "cuda":
            candidates = [("cuda", cfg.stt_compute_type if cfg.stt_compute_type != "auto" else "float16")]
        else:
            candidates = [("cpu", cfg.stt_compute_type if cfg.stt_compute_type != "auto" else "int8")]

        for device, compute_type in candidates:
            model = None
            try:
                model = self._build(device, compute_type)
                self._self_test(model)
                self._model = model
                self._device = device
                self._compute_type = compute_type
                log.info("Whisper cargado en %s/%s", device, compute_type)
                return
            except Exception as exc:  # CUDA puede fallar por libs; se intenta CPU
                errors.append(f"{device}/{compute_type}: {exc}")
                del model

        raise STTError(
            "No pude cargar Whisper. Intentos:\n  " + "\n  ".join(errors)
        )

    def _fallback_cpu(self) -> None:
        """Recarga en CPU si CUDA falla en tiempo de ejecución."""
        log.warning("CUDA falló al transcribir; cambiando a CPU (int8).")
        self._model = None
        self._model = self._build("cpu", "int8")
        self._device = "cpu"
        self._compute_type = "int8"

    def warmup(self) -> None:
        # Si hay GROQ_API_KEY disponible, usamos Whisper-large-v3-turbo en la nube (0 MB RAM/GPU local)
        if os.getenv("GROQ_API_KEY", "").strip():
            return
        with self._lock:
            self._load()

    def _transcribe_groq_cloud(self, audio: np.ndarray, sample_rate: int, api_key: str) -> str | None:
        """Transcribe audio en la nube con Groq (whisper-large-v3-turbo) sin consumir RAM ni GPU local."""
        import io
        import json
        import urllib.request
        import wave

        try:
            pcm16 = np.clip(audio * 32767.0, -32768, 32767).astype(np.int16)
            wav_buf = io.BytesIO()
            with wave.open(wav_buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(pcm16.tobytes())
            wav_bytes = wav_buf.getvalue()

            boundary = "----CloeGroqAudioBoundary987654321"
            parts: list[bytes] = []

            def _add_field(name: str, val: str):
                parts.append(f"--{boundary}\r\n".encode("utf-8"))
                parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
                parts.append(f"{val}\r\n".encode("utf-8"))

            _add_field("model", "whisper-large-v3-turbo")
            _add_field("language", self.config.stt_language or "es")
            _add_field("response_format", "json")

            parts.append(f"--{boundary}\r\n".encode("utf-8"))
            parts.append(
                b'Content-Disposition: form-data; name="file"; filename="speech.wav"\r\n'
                b"Content-Type: audio/wav\r\n\r\n"
            )
            parts.append(wav_bytes)
            parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
            body = b"".join(parts)

            req = urllib.request.Request(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                data=body,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                    "User-Agent": "CloeAssistant/2.0",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            return (data.get("text") or "").strip()
        except Exception as exc:
            log.warning("Groq STT no disponible (%s), usando Whisper local...", exc)
            return None

    def _run(self, audio: np.ndarray) -> str:
        assert self._model is not None
        segments, _info = self._model.transcribe(
            audio,
            language=self.config.stt_language,
            beam_size=max(1, self.config.stt_beam_size),
            best_of=1,
            temperature=0.0,
            condition_on_previous_text=False,
            initial_prompt=self.config.stt_initial_prompt or None,
            vad_filter=True,
            vad_parameters={
                "min_silence_duration_ms": 300,
                "speech_pad_ms": 200,
            },
            without_timestamps=True,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        if audio is None or audio.size == 0:
            return ""
        audio = audio.astype(np.float32, copy=False)
        if sample_rate != 16000:
            audio = resample_linear(audio, sample_rate, 16000)

        groq_key = os.getenv("GROQ_API_KEY", "").strip()
        if groq_key:
            cloud_text = self._transcribe_groq_cloud(audio, 16000, groq_key)
            if cloud_text is not None:
                return cloud_text.replace("Chloe", "Cloe").replace("chloe", "Cloe")

        with self._lock:
            self._load()
            try:
                text = self._run(audio)
            except RuntimeError as exc:
                message = str(exc).lower()
                cuda_issue = any(
                    token in message
                    for token in ("cublas", "cudnn", "cuda", "gpu")
                )
                if self._device != "cuda" or not cuda_issue:
                    raise
                self._fallback_cpu()
                text = self._run(audio)

        # Un pequeño post-proceso para nombres propios que Whisper confunde.
        if text:
            text = text.replace("Chloe", "Cloe").replace("chloe", "Cloe")
        return text

    def close(self) -> None:
        with self._lock:
            self._model = None


class CloudSTT(STTEngine):
    """Punto de extensión para STT en la nube.

    Implementa `transcribe()` llamando a tu proveedor (OpenAI, Deepgram,
    Gemini, etc.) y registra la clase en `create_stt`.
    """

    def __init__(self, provider: str):
        raise STTError(
            f"El proveedor STT '{provider}' todavía no está implementado. "
            "La interfaz STTEngine está lista para añadirlo sin tocar a Cloe."
        )


def create_stt(config: VoiceConfig) -> STTEngine:
    if config.stt_provider == "local":
        return FasterWhisperSTT(config)
    if config.stt_provider == "cloud":
        return CloudSTT(config.stt_provider)
    raise STTError(f"Proveedor STT desconocido: {config.stt_provider}")
