"""Entrada y salida de audio sin dependencias de PortAudio.

Usa PipeWire (pw-record / pw-play) cuando está disponible y cae a ALSA
(arecord / aplay) o PulseAudio (paplay). Así funciona igual en la PC de
desarrollo y en un servidor headless.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import threading
import wave
from collections import deque
from pathlib import Path
from typing import Callable

import numpy as np

from .config import VoiceConfig

log = logging.getLogger("cloe.voice")


class AudioError(RuntimeError):
    """No se pudo abrir el micrófono, el altavoz o el formato de audio."""


# ── Utilidades de audio ───────────────────────────────────────────────────────

def rms(audio: np.ndarray) -> float:
    """RMS normalizado (0-1) de una señal float32."""
    if audio.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))


def speech_band_rms(
    audio: np.ndarray,
    sr: int,
    low: float = 300.0,
    high: float = 3400.0,
) -> float:
    """RMS de la banda de voz (300-3400 Hz).

    Ignora el ruido grave de ventiladores, motores o tráfico, que en un
    micrófono con ganancia alta puede superar el umbral de energía total.
    """
    if audio.size == 0:
        return 0.0
    window = np.hanning(len(audio))
    spectrum = np.fft.rfft(audio.astype(np.float64) * window)
    freqs = np.fft.rfftfreq(len(audio), 1.0 / sr)
    spectrum[(freqs < low) | (freqs > high)] = 0.0
    filtered = np.fft.irfft(spectrum, n=len(audio))
    return rms(filtered)


def resample_linear(audio: np.ndarray, sr_from: int, sr_to: int = 16000) -> np.ndarray:
    """Remuestreo lineal suficiente para voz; evita depender de scipy."""
    if sr_from == sr_to or audio.size == 0:
        return audio.astype(np.float32, copy=False)
    n = int(round(len(audio) * sr_to / sr_from))
    if n <= 0:
        return np.zeros(0, dtype=np.float32)
    idx = np.linspace(0, len(audio) - 1, n)
    return np.interp(idx, np.arange(len(audio)), audio).astype(np.float32)


def read_wav(path: str | os.PathLike[str]) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        channels = w.getnchannels()
        width = w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width != 2:
        raise AudioError(f"Solo se admiten WAV PCM 16-bit (recibido {width * 8}-bit)")
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    return audio, sr


def write_wav(
    path: str | os.PathLike[str],
    audio: np.ndarray,
    sr: int = 16000,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    clipped = np.clip(audio, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return path


def wav_bytes(audio: np.ndarray, sr: int = 16000) -> bytes:
    """Genera un WAV en memoria (para devolverlo por red o reproducirlo)."""
    import io

    buf = io.BytesIO()
    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype(np.int16)
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


# ── Micrófono ────────────────────────────────────────────────────────────────

def _record_command(config: VoiceConfig) -> list[str]:
    if shutil.which("pw-record"):
        cmd = [
            "pw-record",
            "--rate", str(config.sample_rate),
            "--channels", "1",
            "--format", "s16",
            "--latency", "50ms",
        ]
        if config.input_target:
            cmd += ["--target", config.input_target]
        cmd += ["-a", "-"]
        return cmd

    if shutil.which("arecord"):
        cmd = [
            "arecord", "-q", "-t", "raw",
            "-f", "S16_LE",
            "-r", str(config.sample_rate),
            "-c", "1",
        ]
        if config.input_target:
            cmd += ["-D", config.input_target]
        cmd.append("-")
        return cmd

    raise AudioError(
        "No encontré pw-record ni arecord. Instala PipeWire o ALSA-utils."
    )


def _terminate(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            pass


_cached_noise_floor: float | None = None


def record_until_silence(
    config: VoiceConfig,
    on_level: Callable[[float, str], None] | None = None,
    should_stop: threading.Event | None = None,
) -> np.ndarray:
    """Graba hasta detectar silencio. Devuelve audio float32 mono a 16 kHz.

    La máquina de estados:
      - calibra el ruido ambiente (rápido si ya hay suelo en caché de turnos previos);
      - mide energía solo en la banda de voz (300-3400 Hz);
      - espera voz con un umbral adaptativo (ruido × factor) y pre-roll;
      - al detectarla, acumula;
      - cierra el turno tras `silence_ms` de silencio;
      - descarta ruidos que no alcanzan el pico mínimo de voz;
      - cancela si no hablas en `no_speech_timeout_s`.
    """
    global _cached_noise_floor
    sr = config.sample_rate
    frame_samples = max(1, int(sr * config.frame_ms / 1000))
    frame_bytes = frame_samples * 2
    pre_roll_frames = max(1, int(300 / config.frame_ms))
    full_cal_frames = max(1, int(config.noise_calibration_ms / config.frame_ms))
    calibration_frames = 3 if _cached_noise_floor is not None else full_cal_frames
    max_frames = max(1, int(config.max_record_s * 1000 / config.frame_ms))
    no_speech_frames = int(config.no_speech_timeout_s * 1000 / config.frame_ms)
    min_speech_frames = max(1, int(config.min_speech_ms / config.frame_ms))
    silence_frames_needed = max(1, int(config.silence_ms / config.frame_ms))
    start_consecutive = max(1, config.start_consecutive_frames)

    cmd = _record_command(config)
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )
    except OSError as exc:
        raise AudioError(f"No pude abrir el micrófono: {exc}") from exc

    assert proc.stdout is not None
    pre_roll: deque[np.ndarray] = deque(
        maxlen=calibration_frames + pre_roll_frames
    )
    frames: list[np.ndarray] = []
    started = False
    speech_frames = 0
    silence_frames = 0
    run_frames = 0
    total_frames = 0
    peak_level = 0.0
    loud_frames = 0
    noise_levels: list[float] = []
    start_threshold = config.speech_threshold
    sustain_threshold = config.speech_threshold * 0.7

    def read_frame() -> tuple[np.ndarray | None, float]:
        nonlocal total_frames
        raw = proc.stdout.read(frame_bytes)
        if not raw:
            return None, 0.0
        if len(raw) < frame_bytes:
            # Última lectura parcial; se completa con ceros.
            raw += b"\x00" * (frame_bytes - len(raw))
        frame = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        total_frames += 1
        return frame, speech_band_rms(frame, sr)

    try:
        # 1) Calibración: mide el ruido de fondo antes de decidir el umbral.
        for _ in range(calibration_frames):
            if should_stop is not None and should_stop.is_set():
                break
            frame, level = read_frame()
            if frame is None:
                break
            pre_roll.append(frame)
            noise_levels.append(level)
            if on_level is not None:
                on_level(level, "calibrating")

        if noise_levels:
            p25 = float(np.percentile(noise_levels, 25))
            p50 = float(np.percentile(noise_levels, 50))
            measured_floor = min(p50, p25 * 1.5)
            if _cached_noise_floor is None:
                noise_floor = measured_floor
            else:
                # Si el usuario empezó a hablar de inmediato, no inflar el suelo de ruido
                if measured_floor <= _cached_noise_floor * 2.0:
                    noise_floor = 0.75 * _cached_noise_floor + 0.25 * measured_floor
                else:
                    noise_floor = _cached_noise_floor
            _cached_noise_floor = noise_floor

            start_threshold = max(
                config.speech_threshold, noise_floor * config.noise_multiplier
            )
            start_threshold = min(start_threshold, config.max_speech_threshold)
            sustain_threshold = max(
                config.speech_threshold * 0.7,
                noise_floor * config.noise_sustain_multiplier,
            )
            sustain_threshold = min(sustain_threshold, start_threshold * 0.8)
            log.debug(
                "VAD calibrado: ruido=%.4f inicio=%.4f sosten=%.4f",
                noise_floor, start_threshold, sustain_threshold,
            )

        # 2) Revisa si ya había voz durante la calibración.
        for level in noise_levels:
            if not started:
                if level >= start_threshold:
                    run_frames += 1
                    if run_frames >= start_consecutive:
                        started = True
                        speech_frames = run_frames
                        silence_frames = 0
                else:
                    run_frames = 0
            else:
                peak_level = max(peak_level, level)
                if level >= sustain_threshold:
                    speech_frames += 1
                    silence_frames = 0
                else:
                    silence_frames += 1
                if level >= start_threshold * config.peak_ratio:
                    loud_frames += 1
        if started:
            frames.extend(pre_roll)

        # 3) Sigue leyendo hasta silencio, timeout o duración máxima.
        while True:
            if should_stop is not None and should_stop.is_set():
                break
            frame, level = read_frame()
            if frame is None:
                break

            if on_level is not None:
                on_level(level, "speech" if started else "waiting")

            if not started:
                pre_roll.append(frame)
                if level >= start_threshold:
                    run_frames += 1
                    if run_frames >= start_consecutive:
                        started = True
                        speech_frames = run_frames
                        silence_frames = 0
                        frames.extend(pre_roll)
                else:
                    run_frames = 0
                    if total_frames >= no_speech_frames:
                        break
            else:
                frames.append(frame)
                peak_level = max(peak_level, level)
                if level >= sustain_threshold:
                    speech_frames += 1
                    silence_frames = 0
                else:
                    silence_frames += 1
                if level >= start_threshold * config.peak_ratio:
                    loud_frames += 1
                if silence_frames >= silence_frames_needed:
                    if speech_frames >= min_speech_frames:
                        break
                    # Silencio tras un ruido breve: no era voz.
                    frames.clear()
                    started = False
                    break

            if total_frames >= max_frames:
                break
    except KeyboardInterrupt:
        raise
    finally:
        _terminate(proc)

    manual_stop = should_stop is not None and should_stop.is_set()
    if manual_stop and not frames and pre_roll:
        frames.extend(pre_roll)
        started = True

    if not started or not frames:
        return np.zeros(0, dtype=np.float32)

    audio = np.concatenate(frames).astype(np.float32, copy=False)
    if len(audio) < int(sr * config.min_speech_ms / 1000):
        return np.zeros(0, dtype=np.float32)

    # Si el usuario soltó manualmente el botón (push-to-talk), aceptar el audio directo
    if manual_stop:
        if peak_level >= config.speech_threshold * 0.5:
            return audio
        return np.zeros(0, dtype=np.float32)

    # Validación final en modo automático: descarta ruido que superó el umbral pero no es voz.
    if (
        speech_frames < min_speech_frames
        or loud_frames < min_speech_frames
        or peak_level < start_threshold * config.peak_ratio
    ):
        log.debug(
            "VAD descartado: speech=%d loud=%d pico=%.4f umbral=%.4f",
            speech_frames, loud_frames, peak_level, start_threshold,
        )
        return np.zeros(0, dtype=np.float32)

    log.debug(
        "VAD aceptado: dur=%.2fs speech=%d loud=%d pico=%.4f",
        len(audio) / sr, speech_frames, loud_frames, peak_level,
    )
    return audio


def record_fixed(config: VoiceConfig, seconds: float = 3.0) -> np.ndarray:
    """Graba una duración fija (útil para diagnóstico y pruebas)."""
    sr = config.sample_rate
    cmd = _record_command(config)
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0
    )
    assert proc.stdout is not None
    want = int(sr * seconds) * 2
    raw = b""
    try:
        while len(raw) < want:
            chunk = proc.stdout.read(want - len(raw))
            if not chunk:
                break
            raw += chunk
    finally:
        _terminate(proc)
    return np.frombuffer(raw[:want], dtype=np.int16).astype(np.float32) / 32768.0


# ── Altavoz ──────────────────────────────────────────────────────────────────

def _play_command(config: VoiceConfig, path: str | os.PathLike[str]) -> list[str]:
    if shutil.which("pw-play"):
        cmd = ["pw-play"]
        if config.output_target:
            cmd += ["--target", config.output_target]
        cmd.append(str(path))
        return cmd
    if shutil.which("aplay"):
        cmd = ["aplay", "-q"]
        if config.output_target:
            cmd += ["-D", config.output_target]
        cmd.append(str(path))
        return cmd
    if shutil.which("paplay"):
        cmd = ["paplay"]
        if config.output_target:
            cmd += ["--device", config.output_target]
        cmd.append(str(path))
        return cmd
    raise AudioError("No encontré pw-play, aplay ni paplay para reproducir audio.")


class WavPlayer:
    """Reproductor interrumpible basado en el reproductor del sistema."""

    def __init__(self, config: VoiceConfig):
        self.config = config
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def play_file(self, path: str | os.PathLike[str]) -> None:
        self.stop()
        cmd = _play_command(self.config, path)
        with self._lock:
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            proc = self._proc
        try:
            proc.wait()
        finally:
            with self._lock:
                if self._proc is proc:
                    self._proc = None

    def play_bytes(self, data: bytes, suffix: str = ".wav") -> None:
        if not data:
            return
        fd, path = tempfile.mkstemp(prefix="cloe_voz_", suffix=suffix)
        os.close(fd)
        try:
            Path(path).write_bytes(data)
            self.play_file(path)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def stop(self) -> None:
        with self._lock:
            proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=1.0)
            except (subprocess.TimeoutExpired, OSError):
                try:
                    proc.kill()
                except OSError:
                    pass
        with self._lock:
            self._proc = None

    @property
    def is_playing(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None
