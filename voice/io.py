"""Fachada de voz: une micrófono, transcripción y síntesis en un solo objeto."""

from __future__ import annotations

import logging
import queue
import threading
from typing import Callable

import numpy as np

from .audio import record_until_silence
from .config import VoiceConfig
from .stt import STTEngine, create_stt
from .text import clean_for_speech, pop_streaming_sentence, split_for_speech
from .tts import TTSEngine, create_tts

log = logging.getLogger("cloe.voice")


class VoiceError(RuntimeError):
    """La capa de voz no está disponible o falló."""


class SpeechStream:
    """Cola de síntesis y reproducción en tiempo real mientras el LLM genera tokens."""

    def __init__(self, tts: TTSEngine):
        self.tts = tts
        self._buffer = ""
        self._first_chunk = True
        self._aborted = threading.Event()
        self._text_q: queue.Queue[str | None] = queue.Queue()
        self._audio_q: queue.Queue[bytes | None] = queue.Queue(maxsize=3)
        self._synth_thread = threading.Thread(target=self._synth_worker, daemon=True)
        self._play_thread = threading.Thread(target=self._play_worker, daemon=True)
        self._synth_thread.start()
        self._play_thread.start()

    def feed(self, token: str) -> None:
        """Alimenta nuevos tokens del LLM y emite frases completas en cuanto están listas."""
        if self._aborted.is_set() or not token:
            return
        self._buffer += token
        while True:
            sentence, remainder = pop_streaming_sentence(
                self._buffer, first_chunk=self._first_chunk
            )
            self._buffer = remainder
            if sentence is None:
                break
            self._first_chunk = False
            cleaned = clean_for_speech(sentence)
            if cleaned:
                self._text_q.put(cleaned)

    def finish(self, wait: bool = True) -> None:
        """Envía el resto del buffer y espera a que termine de hablar."""
        if not self._aborted.is_set():
            tail = self._buffer.strip()
            self._buffer = ""
            if tail and not tail.lstrip().startswith("{"):
                for part in split_for_speech(tail):
                    if part:
                        self._text_q.put(part)
        self._text_q.put(None)
        if wait:
            self._play_thread.join()

    def abort(self) -> None:
        """Cancela inmediatamente la síntesis y reproducción en curso."""
        self._aborted.set()
        self.tts.stop()
        self._text_q.put(None)
        try:
            while not self._audio_q.empty():
                self._audio_q.get_nowait()
        except queue.Empty:
            pass
        try:
            self._audio_q.put_nowait(None)
        except queue.Full:
            pass

    def _synth_worker(self) -> None:
        try:
            while not self._aborted.is_set():
                sentence = self._text_q.get()
                if sentence is None or self._aborted.is_set():
                    break
                try:
                    with self.tts._synth_lock:
                        if self._aborted.is_set():
                            break
                        audio = self.tts.synthesize(sentence)
                    if audio and not self._aborted.is_set():
                        self._audio_q.put(audio)
                except Exception as exc:
                    log.warning("Error sintetizando en stream: %s", exc)
        finally:
            self._audio_q.put(None)

    def _play_worker(self) -> None:
        suffix = getattr(self.tts, "audio_suffix", ".wav")
        while not self._aborted.is_set():
            audio = self._audio_q.get()
            if audio is None or self._aborted.is_set():
                break
            try:
                self.tts.player.play_bytes(audio, suffix=suffix)
            except Exception as exc:
                log.warning("Error reproduciendo en stream: %s", exc)


class VoiceIO:
    """Entrada/salida de voz independiente de la interfaz (terminal, GUI, web)."""

    def __init__(
        self,
        config: VoiceConfig | None = None,
        stt: STTEngine | None = None,
        tts: TTSEngine | None = None,
    ):
        self.config = config or VoiceConfig.from_env()
        problems = self.config.validate()
        if problems:
            raise VoiceError(
                "Configuración de voz incompleta:\n  - " + "\n  - ".join(problems)
            )
        self.stt = stt or create_stt(self.config)
        self.tts = tts or create_tts(self.config)
        self._closed = False
        self._speak_lock = threading.Lock()
        self._active_stream: SpeechStream | None = None

    # ── Entrada ────────────────────────────────────────────────────────────
    def listen(
        self,
        on_level: Callable[[float, str], None] | None = None,
        should_stop: threading.Event | None = None,
    ) -> str:
        """Graba un turno y devuelve el texto transcrito ('' si no hubo voz)."""
        audio = record_until_silence(
            self.config, on_level=on_level, should_stop=should_stop
        )
        if audio.size == 0:
            return ""
        return self.stt.transcribe(audio, self.config.sample_rate)

    def transcribe(self, audio: np.ndarray, sample_rate: int | None = None) -> str:
        return self.stt.transcribe(
            audio, sample_rate if sample_rate is not None else self.config.sample_rate
        )

    # ── Salida ─────────────────────────────────────────────────────────────
    def speak(self, text: str) -> None:
        """Sintetiza y reproduce por frases; ignora texto vacío."""
        if not text or not text.strip():
            return
        with self._speak_lock:
            self.tts.speak(text)

    def start_stream(self) -> SpeechStream:
        """Inicia una sesión de habla en streaming sincronizada con los tokens del LLM."""
        self.stop_speaking()
        stream = SpeechStream(self.tts)
        self._active_stream = stream
        return stream

    def stop_speaking(self) -> None:
        if self._active_stream is not None:
            self._active_stream.abort()
            self._active_stream = None
        self.tts.stop()

    def reconfigure_tts(
        self,
        engine: str | None = None,
        voice: str | None = None,
        speed: float | None = None,
    ) -> None:
        """Actualiza motor, voz o velocidad en caliente desde la GUI."""
        self.stop_speaking()
        if engine:
            self.config.tts_engine = engine
        if voice:
            if self.config.tts_engine == "edge":
                self.config.edge_voice = voice
            elif self.config.tts_engine == "kokoro":
                self.config.kokoro_voice = voice
            elif self.config.tts_engine == "piper":
                base = self.config.piper_model.parent / f"{voice}.onnx"
                if base.exists():
                    self.config.piper_model = base
                    self.config.piper_config = base.with_name(base.name + ".json")
        if speed is not None:
            self.config.kokoro_speed = speed
            self.config.piper_length_scale = round(max(0.7, min(1.4, 1.0 / speed)), 2)
            pct = int(round((speed - 1.0) * 100))
            self.config.edge_rate = f"{pct:+d}%"
        if engine or voice:
            try:
                old_tts = self.tts
                self.tts = create_tts(self.config)
                old_tts.close()
            except Exception as exc:
                log.warning("No se pudo cambiar el motor TTS a %s: %s", engine, exc)

    # ── Ciclo de vida ──────────────────────────────────────────────────────
    def warmup(self) -> None:
        """Carga el modelo de STT antes de la primera interacción."""
        self.stt.warmup()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.stop_speaking()
        finally:
            self.tts.close()
            self.stt.close()

    @property
    def description(self) -> str:
        stt_name = getattr(self.stt, "name", "stt")
        tts_name = getattr(self.tts, "name", "tts")
        return f"{stt_name} + {tts_name}"

