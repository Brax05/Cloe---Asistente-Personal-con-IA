# Voz y llamadas de Cloe

Esta es la arquitectura propia de Cloe para voz y, más adelante, telefonía.
**No se copió código ni recursos de otros proyectos**: la idea de un asistente
que habla y hace llamadas es libre; lo que se protege es la implementación
concreta de cada repo.

## 1. Qué funciona hoy (voz local)

```
micrófono → VAD adaptativo (300-3400 Hz) → faster-whisper → Ollama (Cloe) → Piper → altavoz
```

- **STT local:** `faster-whisper` (modelo `small` por defecto). Intenta CUDA y
  cae a CPU si faltan librerías de NVIDIA.
- **TTS local:** Kokoro (neural, voz natural, `ef_dora`) por defecto; Piper y espeak como alternativas.
- **VAD adaptativo:** calibra el ruido ambiente, mide energía solo en la banda
  de voz y descarta ruidos que no alcanzan el pico mínimo. Así no se dispara
  con el ventilador ni graba 30 s de silencio.
- **Limpieza:** antes de hablar se quitan kaomojis, markdown, emojis y se
  convierten las líneas `♪ canción - artista` en texto natural.
- **Interfaces:** terminal (`chat.py`) y mascota PyQt6 (`gui/desktop_pet.py`).

## 2. Instalación

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-voice.txt
python -m voice.setup_models          # descarga Piper + voz (~115 MB)
python -m voice.setup_models --whisper # opcional: pre-descarga Whisper
python -m voice.selftest              # sintetiza, reproduce y transcribe
```

Otra voz (por ejemplo la de dominio público `es_MX-ald-medium`):

```bash
python -m voice.setup_models --voice es_MX-ald-medium
# y en .env:
CLOE_PIPER_VOICE=es_MX-ald-medium
```

Si tu sistema no tiene `pip` en el Python del sistema:

```bash
python3 -m venv --without-pip .venv
curl -sS https://bootstrap.pypa.io/get-pip.py | .venv/bin/python
.venv/bin/python -m pip install -r requirements.txt -r requirements-voice.txt
```

### Terminal

```bash
python chat.py --voz
```

- Pulsa **Enter** para hablar; la grabación se cierra sola al detectar silencio.
- También puedes escribir normal; la voz solo se activa con Enter vacío.
- `--voz-continua` para manos libres.
- `--sin-tts` para dictar sin que Cloe hable.
- `--stt-model medium` si quieres más precisión (más lento).
- `--velocidad-voz 1.15` para hablar más despacio.
- `python -m voice.demo_voz` para probar voz a voz sin Ollama.

### Mascota de escritorio

```bash
python gui/desktop_pet.py
```

- Botón **🎤** en el cuadro de texto: graba y transcribe.
- Clic derecho → **Hablar con Cloe**.
- Clic derecho → **Voz de Cloe** para activar/desactivar la salida de voz.
- La voz se carga en segundo plano al arrancar; la ventana no se congela.

## 3. Configuración

Todo se controla con variables `CLOE_*` (ver `.env.example`):

| Variable | Default | Qué hace |
|---|---|---|
| `CLOE_STT_MODEL` | `small` | Modelo de Whisper |
| `CLOE_STT_DEVICE` | `auto` | `auto`, `cuda` o `cpu` |
| `CLOE_STT_LANGUAGE` | `es` | Idioma de transcripción |
| `CLOE_TTS_ENGINE` | `kokoro` | `kokoro`, `piper`, `espeak` o `none` |
| `CLOE_KOKORO_VOICE` | `ef_dora` | Voz de Kokoro (ef_dora, em_alex) |
| `CLOE_KOKORO_SPEED` | `1.0` | Velocidad de Kokoro |
| `CLOE_PIPER_VOICE` | `es_MX-claude-high` | Voz de Piper a usar (debe estar instalada) |
| `CLOE_PIPER_LENGTH_SCALE` | `1.05` | Velocidad (mayor = más lento) |
| `CLOE_MIC_TARGET` | vacío | Fuente PipeWire o dispositivo ALSA |
| `CLOE_SPEAKER_TARGET` | vacío | Salida PipeWire o dispositivo ALSA |
| `CLOE_VOICE_SILENCE_MS` | `900` | Silencio que cierra el turno |
| `CLOE_VOICE_THRESHOLD` | `0.010` | Umbral mínimo de voz (banda 300-3400 Hz) |
| `CLOE_VOICE_CALIBRATION_MS` | `800` | Calibración de ruido ambiente |
| `CLOE_VOICE_NOISE_MULT` | `2.5` | Umbral = ruido × factor al empezar |
| `CLOE_VOICE_NOISE_SUSTAIN` | `1.8` | Umbral para seguir hablando |
| `CLOE_VOICE_START_FRAMES` | `4` | Frames seguidos para confirmar voz |
| `CLOE_VOICE_PEAK_RATIO` | `1.5` | Pico mínimo para validar que es voz |
| `CLOE_VOICE_MAX_THRESHOLD` | `0.080` | Tope del umbral adaptativo |
| `CLOE_SPEAK_SOLO` | `false` | Leer también charlas espontáneas |

Para listar dispositivos:

```bash
wpctl status          # PipeWire
arecord -l            # ALSA
aplay -l
```

### Si el micrófono no entrega señal

En esta laptop (OMEN + PipeWire) el control `Dmic0` estaba al 16 %
(−39 dB) y el micrófono entregaba silencio. Se subió así:

```bash
wpctl status                          # localiza la fuente (Sources)
wpctl set-volume <ID_FUENTE> 1.0
amixer -c 1 sset Dmic0 60             # ajusta la tarjeta/control a tu equipo
amixer -c 1 sset Capture cap,cap
python -m voice.selftest --mic 4      # debe mostrar RMS distinto de cero
```

Si el RMS es alto pero la transcripción sale vacía, puede ser ruido de fondo:
sube `CLOE_VOICE_THRESHOLD` o `CLOE_VOICE_NOISE_MULT`. Si Cloe no detecta tu
voz, baja `CLOE_VOICE_THRESHOLD` (por ejemplo a `0.006`) o
`CLOE_VOICE_NOISE_MULT` (por ejemplo a `2.0`). El VAD mide solo la banda de voz
(300–3400 Hz), así que ignora buena parte del ruido grave de ventiladores y
motores.

## 4. Arquitectura pensada para portar

```
voice/
├── config.py        # parámetros y variables de entorno
├── audio.py         # micrófono/altavoz (PipeWire, ALSA, PulseAudio)
├── stt.py           # STTEngine + FasterWhisperSTT + CloudSTT (extensión)
├── tts.py           # TTSEngine + PiperTTS + EspeakTTS + CloudTTS (extensión)
├── text.py          # limpieza de kaomojis/markdown para hablar
├── io.py            # VoiceIO: fachada única para cualquier interfaz
├── calls.py         # CallBridge: interfaz de telefonía (SIP/WebRTC/Android)
└── setup_models.py  # descarga de binarios y voces
```

Para añadir la nube más adelante **no hay que tocar `chat.py` ni la GUI**:

1. Implementa `CloudSTT.transcribe()` o `CloudTTS.synthesize()` con tu proveedor
   (OpenAI, Gemini, Deepgram, ElevenLabs, Azure…).
2. Regístralo en `create_stt()` / `create_tts()`.
3. Cambia `CLOE_STT_PROVIDER=cloud` o `CLOE_TTS_PROVIDER=cloud`.

La misma fachada `VoiceIO` se puede exponer por WebSocket para que un cliente
Android, una web o otro PC usen el cerebro y la voz de Cloe de forma remota.
Ese es el paso natural para portar el asistente.

## 5. Llamadas reales: interfaz lista, proveedor pendiente

Sin root **no se puede inyectar audio digitalmente** en una llamada celular.
Android no lo permite. Estas son las opciones honestas:

| Ruta | Cómo funciona | Calidad | Root | SIM propia | Portabilidad |
|---|---|---|---|---|---|
| **Altavoz + micrófono** | El celular marca en altavoz; la IA oye por el micrófono y habla por el altavoz | Baja/media (eco) | No | Sí | Alta |
| **Inyección digital** | La app escribe audio en el mezclador de la llamada (`tinyplay`/`tinycap`) | Alta | Sí | Sí | Baja: depende del chip |
| **VoIP/SIP/WebRTC** | La llamada sale por internet con un número virtual | Alta | No | No | Muy alta |

Cloe ya tiene la interfaz `CallBridge` en `voice/calls.py` y la herramienta
`phone_call(número, objetivo)`. El tool solo se expone al modelo cuando hay un
puente disponible; hoy no hay proveedor implementado, así que Cloe no intentará
llamar por su cuenta.

### Contrato de `CallBridge`

```python
class CallBridge:
    available: bool
    def start_call(self, number: str, objective: str = "") -> CallSession: ...
    def end_call(self, call_id: str | None = None) -> None: ...
    def status(self, call_id: str | None = None) -> CallSession | None: ...
    def send_audio(self, call_id: str, pcm: bytes, sample_rate: int = 16000) -> None: ...
    def read_audio(self, call_id: str, timeout_s: float = 0.0) -> bytes: ...
    def close(self) -> None: ...
```

- Audio del puente: **PCM 16 bits little-endian, mono, 16 kHz**.
- `CallSession` guarda número, objetivo, estado, duración y `call_id`.
- Estados: `dialing`, `ringing`, `active`, `ended`, `failed`.
- `CallConfig` lee `CLOE_CALL_PROVIDER`, `CLOE_CALL_MAX_DURATION_S` y
  `CLOE_CALL_ALLOWLIST`; normaliza y valida números en formato internacional.
- `CLOE_CALL_ALLOWLIST` vacío permite cualquier número válido. En producción,
  define una lista blanca.

### Cómo añadir un proveedor

```python
from voice.calls import CallBridge, register_call_provider

class SipBridge(CallBridge):
    name = "SIP"
    provider = "sip"

    @property
    def available(self) -> bool:
        return True

    def start_call(self, number, objective=""):
        session = self.new_session(number, objective)
        # marcar por SIP y actualizar session.state
        return session

    def end_call(self, call_id=None):
        session = self.status(call_id)
        if session:
            self.finish_session(session.call_id)

register_call_provider("sip", lambda config: SipBridge(config))
```

Después define `CLOE_CALL_PROVIDER=sip`. El resto de Cloe no cambia: terminal,
GUI y el modelo siguen usando `phone_call(número, objetivo)`.

### Rutas futuras

- `SpeakerphoneBridge`: app Android propia que marca en altavoz y hace de
  puente acústico (sin root).
- `RootAudioBridge`: app con Magisk que inyecta audio digital (mejor calidad).
- `SipBridge`: llamada por VoIP (sin SIM, máxima portabilidad).

## 6. Licencias de voz

- **Piper** es MIT.
- **Whisper / faster-whisper** son MIT.
- Cada voz de Piper tiene su propio `MODEL_CARD` y licencia de dataset. La voz
  por defecto (`es_MX-claude-high`) declara dataset **Apache-2.0**.
- Antes de vender o distribuir, revisa la licencia de la voz concreta que
  elijas. Si necesitas máxima libertad, `es_MX-ald-medium` declara
  **Unlicense** (dominio público).

## 7. Uso responsable de llamadas

- La IA debe presentarse como IA en la primera frase.
- Llama solo a números propios o de personas que aceptaron.
- Nada de spam, fraude, suplantación ni grabaciones sin aviso.
- Pon topes de duración y de llamadas por día desde el primer prototipo.
