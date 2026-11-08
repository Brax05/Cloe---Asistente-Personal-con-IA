"""Prueba de humo de la voz de Cloe, sin necesidad de hablar.

    python -m voice.selftest            # sintetiza, transcribe y reproduce
    python -m voice.selftest --no-play  # sin altavoz
    python -m voice.selftest --mic 3    # además prueba tu micrófono 3 s
"""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

from .audio import read_wav, rms
from .config import VoiceConfig
from .io import VoiceIO
from .text import clean_for_speech


SAMPLE = "(=^▽^=)ノ **Hola**, soy Cloe. Esta es una prueba de mi voz natural. ฅ^•ﻌ•^ฅ"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Autodiagnóstico de la voz de Cloe")
    parser.add_argument("--no-play", action="store_true", help="no reproducir audio")
    parser.add_argument("--mic", type=float, default=0, metavar="SEGUNDOS",
                        help="probar también el micrófono durante N segundos")
    args = parser.parse_args(argv)

    print("1) Limpieza de texto")
    cleaned = clean_for_speech(SAMPLE)
    print(f"   antes:  {SAMPLE!r}")
    print(f"   después: {cleaned!r}")
    if "=" in cleaned or "ω" in cleaned:
        print("   ✗ quedaron restos de kaomoji")
        return 1
    print("   ✓ texto limpio\n")

    config = VoiceConfig.from_env()
    print(f"2) Iniciando motores ({config.stt_model} + {config.tts_engine})...")
    voice = VoiceIO(config)
    path: str | None = None
    try:
        print("   ✓ motores cargados\n")

        print(f"3) Síntesis de voz ({config.tts_engine})")
        wav = voice.tts.synthesize(cleaned)
        if not wav:
            print(f"   ✗ {config.tts_engine} devolvió audio vacío")
            return 1
        fd, path = tempfile.mkstemp(prefix="cloe_selftest_", suffix=".wav")
        os.close(fd)
        Path(path).write_bytes(wav)
        print(f"   ✓ {len(wav) / 1024:.1f} KB de audio")

        if not args.no_play:
            print("   ▶ reproduciendo por el altavoz...")
            voice.tts.speak(cleaned)

        print("\n4) Transcripción (faster-whisper)")
        audio, sr = read_wav(path)
        text = voice.transcribe(audio, sr)
        print(f"   texto: {text!r}")
        if not text:
            print("   ✗ la transcripción salió vacía")
            return 1
        print("   ✓ el pipeline voz → texto funciona")

        if args.mic > 0:
            print(f"\n5) Micrófono durante {args.mic:.1f} s")
            from .audio import record_fixed
            mic = record_fixed(config, args.mic)
            level = rms(mic)
            print(f"   RMS={level:.5f}  peak={float(abs(mic).max()) if mic.size else 0:.4f}")
            if mic.size == 0 or level < 1e-5:
                print("   ✗ no llegó audio del micrófono (revisa el silenciador o la fuente)")
            else:
                print("   ✓ el micrófono entrega señal")
                heard = voice.transcribe(mic, config.sample_rate)
                print(f"   transcripción: {heard!r}")

        print("\nTodo listo. Arranca Cloe con:  python chat.py --voz")
        return 0
    finally:
        if path:
            try:
                Path(path).unlink()
            except OSError:
                pass
        voice.close()


if __name__ == "__main__":
    raise SystemExit(main())
