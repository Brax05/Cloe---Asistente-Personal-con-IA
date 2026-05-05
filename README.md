# Cloe — Asistente Personal con IA (=^◡^=)

> Asistente personal local basada en **llama 3.1** via Ollama, con personalidad propia, sistema emocional de kaomojis y deteccion autonoma de intencion para controlar servicios externos.

---

## Caracteristica principal

### Deteccion de intencion y respuesta autonoma

Cloe no espera comandos explicitos. Analiza el contexto de la conversacion y actua por cuenta propia:

- Si el usuario menciona musica o un estado de animo → Cloe busca y reproduce en Spotify sin que se lo pidan
- Si hay un evento proximo en el calendario → lo menciona de forma natural
- Si llega un correo importante → lo comenta en contexto
- Genera mensajes espontaneos periodicos por su propia iniciativa

Esto se logra mediante **tool calling nativo** sobre llama 3.1 con un sistema de deteccion de contexto y un dispatcher de herramientas modular.

---

## Funcionalidades

| Servicio | Acciones disponibles |
|---|---|
| Spotify | Reproducir, pausar, siguiente, anterior, volumen, recomendaciones por mood |
| Google Calendar | Ver agenda del dia, proximos eventos, crear eventos |
| Gmail | Leer correos no leidos, enviar correos |
| Autonomia | Habla sola cada cierto tiempo, detecta contexto sin comandos explicitos |

---

## Interfaces

**Terminal**
```bash
python chat.py
```

**Desktop Pet** — ventana flotante transparente, siempre encima del escritorio
```bash
python gui/desktop_pet.py
```

---

## Arquitectura

```
cloe/
├── chat.py                  # Backend principal + terminal
├── tools.py                 # Definiciones de tools para ollama + dispatcher
├── Modelfile                # Personalidad, kaomojis y parametros del modelo
├── gui/
│   └── desktop_pet.py       # Desktop pet con PyQt6
└── services/
    ├── spotify_tools.py     # Integracion Spotify API
    ├── calendar_tools.py    # Google Calendar API
    ├── gmail_tools.py       # Gmail API
    └── google_auth.py       # OAuth2 Google
```

---

## Stack

![Python](https://img.shields.io/badge/Python-3776AB?style=flat&logo=python&logoColor=white)
![Ollama](https://img.shields.io/badge/Ollama-000000?style=flat&logo=ollama&logoColor=white)
![LLaMA](https://img.shields.io/badge/LLaMA_3.1-7B3FE4?style=flat&logo=meta&logoColor=white)
![PyQt6](https://img.shields.io/badge/PyQt6-41CD52?style=flat&logo=qt&logoColor=white)
![Spotify](https://img.shields.io/badge/Spotify_API-1DB954?style=flat&logo=spotify&logoColor=white)
![Google](https://img.shields.io/badge/Google_APIs-4285F4?style=flat&logo=google&logoColor=white)

---

## Setup

### 1. Requisitos
```bash
pip install -r requirements.txt
```

### 2. Variables de entorno
Copia `.env.example` a `.env` y rellena:
```env
SPOTIFY_CLIENT_ID=...
SPOTIFY_CLIENT_SECRET=...
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8888/callback

GOOGLE_CREDENTIALS_PATH=credentials.json
TIMEZONE=America/Mexico_City
```

### 3. Spotify
Crea una app en [developer.spotify.com](https://developer.spotify.com/dashboard) y agrega `http://127.0.0.1:8888/callback` como Redirect URI.

### 4. Google (opcional)
Descarga `credentials.json` desde Google Cloud Console con Calendar y Gmail API habilitadas.

### 5. Compilar el modelo
```bash
ollama create cloe -f Modelfile
```

---

## Sistema emocional

Cloe usa kaomojis de gato como sistema de expresion emocional — uno por respuesta, elegido segun su estado real:

```
Feliz    →  (=^▽^=)ノ  ฅ^•ﻌ•^ฅ
Curiosa  →  (=^･ω･^=)?  (=^‥^=)...
Sorpresa →  Σ(=^･ω･^=)  (=^Д^=)!?
Carino   →  (=^‥^=)♡   /ᐠ｡ꞈ｡ᐟ\づ♡
Humor    →  ψ(=^･ω･^=)ψ  (= ≧▽≦=)
```

---

## Licencia

MIT
