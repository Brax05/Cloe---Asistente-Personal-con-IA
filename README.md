# Cloe — Asistente Personal con IA & Cyber-Pet (=^◡^=)

> Asistente personal de escritorio para Linux con IA multimodal, voz fluida, visión de pantalla, memoria persistente, control del PC y ejecución segura de terminal. Puede funcionar **100% local con Ollama** o **en la nube gratuita a 0% GPU (Groq / Gemini)**.

---

## 🌟 Características Principales

| Módulo | Descripción | Acciones Clave |
|---|---|---|
| 🐾 **Mascota Flotante (PyQt6)** | Orbe cibernético con expresiones kaomoji reactivas y Always-On-Top | Arrastrable, partículas reactivas, monitor de recursos (RAM/CPU/Ronroneo) |
| 👁️ **Visión de Pantalla & Portapapeles** | Captura y comprende tu escritorio en tiempo real | "Mira mi pantalla", "Explica el error que copié" |
| 🧠 **Memoria & Pomodoro** | Recuerda gustos y datos importantes en `memory.json` | Botón **`🍅` Pomodoro**, temporizadores con anillo animado |
| 💻 **Terminal Segura Linux** | Ejecuta comandos en bash con filtro de seguridad de 3 niveles | Consulta y diagnóstico inmediato; **pide autorización (`✅`/`❌`)** antes de borrar archivos |
| ⚙️ **Control del PC en Linux** | Controla el sistema operativo | Ajuste de volumen (`wpctl`/`pactl`), abrir apps instaladas, estado de batería/disco/RAM/CPU |
| 🌤️ **Clima & Búsqueda Web** | Información en tiempo real sin API keys de pago | Clima en vivo vía Open-Meteo y noticias/búsqueda web vía DuckDuckGo |
| 🎵 **Spotify & Google** | Control total de música, correo y agenda | Playlists, reproducción, cola, agenda Google Calendar y correos Gmail |
| 🎙️ **Voz Natural Fluida** | STT rápido y TTS neural sin pausas | Pulsar para hablar, charla continua manos libres y ajuste de velocidad |

---

## 🚀 Inicio Rápido (Llegar y Probar)

### 1. Clonar el repositorio
```bash
git clone https://github.com/Brax05/Cloe---Asistente-Personal-con-IA.git
cd Cloe---Asistente-Personal-con-IA
```

### 2. Crear entorno virtual e instalar dependencias
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

*(Opcional para voz local offline con Piper/Kokoro)*:
```bash
pip install -r requirements-voice.txt
python -m voice.setup_models
```

---

### 3. Configurar `.env` (Elige tu Motor de IA)

Copia la plantilla de configuración:
```bash
cp .env.example .env
```

Abre `.env` y elige cómo quieres ejecutar el cerebro de Cloe:

#### ⚡ Opción A: Nube Gratuita a 0% GPU (Recomendada, ultra rápida)
Obtén una API key gratuita en [console.groq.com/keys](https://console.groq.com/keys) o [aistudio.google.com/apikey](https://aistudio.google.com/apikey):
```env
CLOE_LLM_PROVIDER=auto
GROQ_API_KEY=gsk_tu_api_key_aqui
CLOE_GROQ_MODEL=llama-3.3-70b-versatile
```

#### 🖥️ Opción B: 100% Local y Privado con Ollama
Si prefieres que todo corra en tu propio hardware sin internet:
1. Instala Ollama y crea el modelo:
   ```bash
   ollama create cloe -f Modelfile
   ```
2. En `.env`:
   ```env
   CLOE_LLM_PROVIDER=ollama
   CLOE_OLLAMA_MODEL=cloe
   ```

---

### 4. Iniciar Cloe

#### 🐾 Modo Mascota de Escritorio (GUI Interactiva)
```bash
./run_gui.sh
```

#### 📟 Modo Consola / Terminal
```bash
./run_chat.sh
```

---

## 🎮 Guía para Probar a Cloe

Una vez abierta la mascota de escritorio:

### 1. Interacción con el Orbe
- **1 Clic corto**: Acaricias a Cloe (aumenta el ronroneo `♥` y abre la burbuja lateral).
- **Mantener presionado**: Habla mientras mantienes presionado; al soltar, Cloe procesará tu voz y responderá.
- **Doble clic rápido**: Activa el **modo charla continua manos libres** (el orbe brilla en modo escucha permanente).
- **Arrastrar**: Haz clic y arrastra el orbe o el dock a cualquier lugar de la pantalla.

### 2. Dock de Acciones Rápidas (Debajo del Orbe)
- **`♥`**: Acariciar lomo y aumentar nivel de ronroneo.
- **`🐟`**: Alimentar con cyber-atún (+RAM virtual).
- **`🍅`**: Iniciar o cancelar una sesión **Pomodoro de 25 minutos** (muestra cuenta regresiva en el círculo).
- **`🌙`**: **Modo Dormir / No Molestar** (pausa actividad autónoma y silencia interacciones accidentales).
- **`🔊`**: Silenciar / activar la voz de Cloe.
- **`💬`**: Mostrar u ocultar la burbuja lateral de diálogo.

---

## 💬 Frases de Ejemplo para Probar

Pruébalas hablándole con el micrófono o escribiendo en el campo de texto de la burbuja:

- 👁️ **Visión de pantalla**:
  - *"Cloe, mira mi pantalla y dime qué tengo abierto."*
  - *"¿Qué dice el error que tengo en pantalla?"*
- 📋 **Portapapeles**:
  - Copia cualquier texto o código con `Ctrl+C` y dile: *"Explícame lo que acabo de copiar"*.
- 💻 **Terminal Linux**:
  - *"¿Qué archivos tengo en mi carpeta de Descargas?"*
  - *"Crea una carpeta llamada pruebas en mi Escritorio."*
  - *"¿Qué procesos están consumiendo más memoria?"*
  - *Prueba de seguridad*: Si le pides *"Elimina el archivo notas.txt"*, Cloe **no lo borrará a ciegas**; generará una tarjeta interactiva con botones **`✅ Autorizar`** y **`❌ Cancelar`**.
- ⚙️ **Control del Sistema**:
  - *"Sube el volumen al 70%"* o *"Silencia el audio"*.
  - *"Abre la calculadora"* o *"Abre el navegador"*.
  - *"¿Cómo está la batería y la temperatura del equipo?"*
- 🌤️ **Clima y Noticias**:
  - *"¿Qué clima hace hoy?"*
  - *"Busca en internet noticias sobre avances de inteligencia artificial."*
- 🧠 **Memoria**:
  - *"Recuerda que mi lenguaje favorito es Python."*
  - Luego en otra charla: *"¿Cuál era mi lenguaje favorito?"*

---

## 🔗 Conectar Spotify y Google (Opcional)

Cloe incluye integración completa con Spotify (reproducción, playlists, volumen) y Google (Gmail y Google Calendar).

Para vincular tus cuentas personales con el asistente guiado:
```bash
./conectar_cuentas.sh
```

El script verificará tus credenciales y abrirá el navegador para autorizar con un solo clic:
- **Spotify**: Coloca tu `SPOTIFY_CLIENT_ID` y `SPOTIFY_CLIENT_SECRET` en `.env` (obtenidos en [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) con Redirect URI `http://localhost:8888/callback`).
- **Google**: Descarga `credentials.json` desde [Google Cloud Console](https://console.cloud.google.com) (habilitando Google Calendar API y Gmail API en una aplicación tipo Desktop).

---

## 📁 Estructura del Proyecto

```
cloe/
├── chat.py                  # Cerebro conversacional, tool dispatcher y streaming
├── gui/
│   └── desktop_pet.py       # GUI de escritorio Cyber-Neko (PyQt6)
├── services/
│   ├── terminal_tools.py    # Módulo de Terminal Linux con Sandbox y Autorización
│   ├── vision_clipboard_tools.py # Captura de pantalla, ventana activa y portapapeles
│   ├── pc_control_tools.py  # Control de volumen, apps y estado del hardware
│   ├── web_weather_tools.py # Open-Meteo y búsqueda web en vivo
│   ├── memory_tools.py      # Memoria persistente y motor de Pomodoro
│   ├── spotify_tools.py     # Integración con Spotify API
│   ├── calendar_tools.py    # Integración con Google Calendar
│   ├── gmail_tools.py       # Integración con Gmail
│   └── google_auth.py       # Autenticación OAuth2 de Google
├── voice/                   # Módulo de voz (STT Whisper + TTS Edge/Kokoro/Piper)
├── conectar_cuentas.py      # Asistente interactivo de autorización de cuentas
├── conectar_cuentas.sh      # Acceso directo para autorizar cuentas
├── run_gui.sh               # Lanzador de la mascota de escritorio
└── run_chat.sh              # Lanzador en modo terminal
```

---

## 📜 Licencia

Distribuido bajo la licencia MIT. Consulta el archivo `LICENSE` para más detalles.
