"""Demostración de voz a voz sin LLM.

    python -m voice.demo_voz

Escucha tu voz, la transcribe y responde por voz. Útil para probar el
pipeline completo (micrófono + VAD + STT + TTS + altavoz) sin Ollama.

Si tienes Ollama y el modelo `cloe`, usa en su lugar:
    python chat.py --voz
"""

from __future__ import annotations

import time

from .config import VoiceConfig
from .io import VoiceIO


def respuesta(texto: str) -> str:
    t = texto.lower().strip()
    if not t:
        return "No te escuché. Intenta de nuevo."
    if "hola" in t:
        return "¡Hola! ¿En qué te ayudo hoy?"
    if "nombre" in t:
        return "Soy Cloe, tu asistente personal."
    if "como estas" in t or "cómo estás" in t:
        return "Muy bien, gracias por preguntar. ¿Y tú?"
    if "salir" in t or "adios" in t or "adiós" in t:
        return "Hasta luego. Fue un gusto hablar contigo."
    return f"Te escuché decir: {texto}. Repito: {texto}."


def main() -> int:
    print("Cargando voz...")
    voice = VoiceIO(VoiceConfig.from_env())
    voice.warmup()
    print(f"  ✓ {voice.description}")
    voice.speak("Hola, soy Cloe. Habla cuando quieras. Di 'salir' para terminar.")

    try:
        while True:
            print("\n🎤 Escuchando...")
            texto = voice.listen()
            print(f"Tú: {texto!r}")
            resp = respuesta(texto)
            print(f"Cloe: {resp}")
            # Pequeña pausa para que el micrófono no capte el eco del altavoz.
            time.sleep(0.4)
            voice.speak(resp)
            if any(w in texto.lower() for w in ("salir", "adios", "adiós")):
                break
    except KeyboardInterrupt:
        print("\nInterrumpido.")
    finally:
        voice.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
