import sys
import os
import json
import logging
import random
from datetime import datetime
from dotenv import load_dotenv

# Añadir raíz del proyecto al path para imports
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

load_dotenv(os.path.join(_ROOT, ".env"), override=True)
logging.getLogger("spotipy").setLevel(logging.CRITICAL)
logging.getLogger("urllib3").setLevel(logging.CRITICAL)

from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit,
    QPushButton, QVBoxLayout, QHBoxLayout, QFrame, QMenu,
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QPoint, QTimer,
    QPropertyAnimation, QEasingCurve, pyqtProperty,
)
from PyQt6.QtGui import (
    QPainter, QPainterPath, QColor, QLinearGradient,
    QRadialGradient, QFont, QAction,
)

import ollama
from chat import (
    connect_services, get_modelfile_system, build_tool_hints,
    extract_inline_tool_calls, detect_songs, is_music_context,
    OLLAMA_HOST, MODEL,
)
from tools import ToolDispatcher, available_tool_names
from services.spotify_tools import play_track
import speech_recognition as sr
import sounddevice as sd
import numpy as np
import queue


# ── Animación de kaomojis ──────────────────────────────────────────────────────
# Prompts que Cloe se manda a sí misma para hablar sola
SOLO_PROMPTS = [
    "Manda UN kaomoji de gatita con un comentario muy corto y gracioso para molestar un poco. Máximo 1 oración.",
    "Di algo random e inesperado, como si de repente se te ocurrió algo. Muy corto, máximo 1 oración.",
    "Manda solo un kaomoji expresivo sin texto.",
    "Dí algo gracioso o un chiste cortísimo. 1 oración máximo.",
    "Comenta algo sobre lo que estás 'haciendo' en este momento como si fueras real. Muy corto.",
    "Manda un kaomoji y una queja pequeña o comentario tonto. 1 oración.",
    "Di algo curioso o raro que se te ocurrió. Cortísimo.",
    "Haz como que te asustaste de algo. Kaomoji + 1 oración.",
    "Manda algo cariñoso y molestoso a la vez. 1 oración máximo.",
    "Comenta el clima o la hora como si te importara mucho. Muy corto.",
]

IDLE_FACES = [
    "(=^◡^=)", "(=^‥^=)", "(=^.^=)", "(=^-ω-^=)",
    "/ᐠ｡ꞈ｡ᐟ\\", "(=^ᆺ^=)", "ฅ^•ﻌ•^ฅ", "(=^･ω･^=)",
]
THINK_FACES = ["(=^._.^=)...", "(=｀-´=)...", "(=^‥^=).。oO"]
HAPPY_FACES = ["(=^▽^=)!", "(=^◡^=)♡", "ヽ(=^･ω･^=)丿"]


# ── Worker ─────────────────────────────────────────────────────────────────────
class CloeWorker(QThread):
    response_ready = pyqtSignal(str)

    def __init__(self, client, messages, tools, dispatcher, user_input):
        super().__init__()
        self.client     = client
        self.messages   = messages
        self.tools      = tools
        self.dispatcher = dispatcher
        self.user_input = user_input

    def run(self):
        try:
            self.messages.append({"role": "user", "content": self.user_input})
            reply = self._tool_loop()
            self.messages.append({"role": "assistant", "content": reply})
            self.response_ready.emit(reply)
        except Exception as e:
            self.response_ready.emit(f"(error: {e})")

    def _tool_loop(self) -> str:
        response  = self.client.chat(model=MODEL, messages=self.messages, tools=self.tools)
        reply_msg = response.message
        for _ in range(6):
            content   = reply_msg.content or ""
            api_calls = getattr(reply_msg, "tool_calls", None) or []
            clean, text_calls = extract_inline_tool_calls(content)
            if not api_calls and not text_calls:
                break
            if api_calls:
                self.messages.append({"role": "assistant", "content": clean, "tool_calls": api_calls})
                for tc in api_calls:
                    name = tc.function.name
                    args = self._clean(tc.function.arguments or {})
                    self.messages.append({"role": "tool", "content": self.dispatcher.run(name, args)})
            if text_calls and not api_calls:
                self.messages.append({"role": "assistant", "content": clean})
                for name, args in text_calls:
                    self.messages.append({"role": "tool", "content": self.dispatcher.run(name, self._clean(args))})
            response  = self.client.chat(model=MODEL, messages=self.messages, tools=self.tools)
            reply_msg = response.message
        return reply_msg.content or ""

    @staticmethod
    def _clean(args) -> dict:
        if isinstance(args, str):
            try: args = json.loads(args)
            except: return {}
        if not isinstance(args, dict): return {}
        return {k: v for k, v in args.items()
                if isinstance(k, str) and k.isidentifier() and v not in (None, "", [])}


# ── Burbuja de diálogo ─────────────────────────────────────────────────────────
class SpeechBubble(QWidget):
    MAX_W  = 300
    TAIL_H = 14

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint |
                         Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._opacity  = 1.0
        self._timer    = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._start_fade)
        self._anim     = None
        self._label    = QLabel(self)
        self._label.setWordWrap(True)
        self._label.setMaximumWidth(self.MAX_W - 24)
        self._label.setStyleSheet("color: #1a1a2e; font-size: 13px; background: transparent;")
        self._label.setFont(QFont("Segoe UI", 10))

    # ── API pública ─────────────────────────────────────────────────────────
    def show_text(self, text: str, pet_rect, auto_hide_ms: int = 8000):
        self._timer.stop()
        self._label.setText(text)
        self._label.adjustSize()
        w = min(self._label.sizeHint().width() + 28, self.MAX_W)
        h = self._label.sizeHint().height() + 20 + self.TAIL_H
        self.setFixedSize(w, h)
        self._label.setGeometry(12, 10, w - 24, h - 10 - self.TAIL_H)
        # Posicionar encima del pet
        cx  = pet_rect.center().x()
        top = pet_rect.top() - h - 4
        self.move(cx - w // 2, top)
        self._set_opacity(1.0)
        self.show()
        self._timer.start(auto_hide_ms)

    def hide_now(self):
        self._timer.stop()
        self.hide()

    def reposition(self, pet_rect):
        cx  = pet_rect.center().x()
        top = pet_rect.top() - self.height() - 4
        self.move(cx - self.width() // 2, top)

    # ── Pintar ──────────────────────────────────────────────────────────────
    def paintEvent(self, _):
        w, h = self.width(), self.height()
        bh   = h - self.TAIL_H
        p    = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(self._opacity)
        path = QPainterPath()
        path.addRoundedRect(0, 0, w, bh, 12, 12)
        # cola apuntando hacia abajo
        path.moveTo(w // 2 - 8, bh)
        path.lineTo(w // 2, bh + self.TAIL_H)
        path.lineTo(w // 2 + 8, bh)
        path.closeSubpath()
        p.fillPath(path, QColor(240, 240, 255, 235))
        p.setPen(QColor(180, 160, 230, 180))
        p.drawPath(path)

    # ── Fade ────────────────────────────────────────────────────────────────
    def _start_fade(self):
        self._anim = QPropertyAnimation(self, b"opacity_prop", self)
        self._anim.setDuration(600)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.setEasingCurve(QEasingCurve.Type.InQuad)
        self._anim.finished.connect(self.hide)
        self._anim.start()

    def _set_opacity(self, v: float):
        self._opacity = v
        self.update()

    def _get_opacity(self) -> float:
        return self._opacity

    opacity_prop = pyqtProperty(float, _get_opacity, _set_opacity)


# ── Input popup ────────────────────────────────────────────────────────────────
class InputPopup(QWidget):
    submitted = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint |
                         Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(280, 48)

        frame = QFrame(self)
        frame.setGeometry(0, 0, 280, 48)
        frame.setStyleSheet("""
            QFrame { background-color: rgba(22, 22, 38, 235);
                     border-radius: 24px; border: 1px solid rgba(140,90,246,120); }
        """)
        hl = QHBoxLayout(frame)
        hl.setContentsMargins(14, 6, 8, 6)
        hl.setSpacing(6)

        self._field = QLineEdit()
        self._field.setPlaceholderText("Escríbele a Cloe...")
        self._field.setStyleSheet("""
            QLineEdit { background: transparent; color: #e8e8f0;
                        border: none; font-size: 13px; }
        """)
        self._field.returnPressed.connect(self._send)

        btn = QPushButton("➤")
        btn.setFixedSize(32, 32)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet("""
            QPushButton { background: #7c3aed; color: white;
                          border-radius: 16px; border: none; font-size: 14px; }
            QPushButton:hover { background: #9c6fff; }
        """)
        btn.clicked.connect(self._send)

        hl.addWidget(self._field)
        hl.addWidget(btn)

    def show_near(self, pet_rect):
        x = pet_rect.center().x() - 140
        y = pet_rect.bottom() + 8
        self.move(x, y)
        self.show()
        self._field.setFocus()
        self._field.clear()
        self._reset_timer()

    def reposition(self, pet_rect):
        x = pet_rect.center().x() - 140
        y = pet_rect.bottom() + 8
        self.move(x, y)

    def _reset_timer(self):
        if not hasattr(self, "_close_timer"):
            self._close_timer = QTimer(self)
            self._close_timer.setSingleShot(True)
            self._close_timer.timeout.connect(self.hide)
            self._field.textChanged.connect(lambda _: self._reset_timer())
        self._close_timer.start(20_000)   # 20 s sin escribir → se cierra

    def _send(self):
        text = self._field.text().strip()
        if text:
            if hasattr(self, "_close_timer"):
                self._close_timer.stop()
            self.hide()
            self.submitted.emit(text)


# ── Voice Worker ───────────────────────────────────────────────────────────────
class VoiceWorker(QThread):
    speech_detected = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._running = True
        self.recognizer = sr.Recognizer()
        self.samplerate = 16000
        self.channels = 1
        self.q = queue.Queue()

    def audio_callback(self, indata, frames, time, status):
        if status:
            pass
        self.q.put(indata.copy())

    def run(self):
        try:
            with sd.InputStream(samplerate=self.samplerate, channels=self.channels, 
                                dtype='int16', callback=self.audio_callback, blocksize=8000):
                print("Micrófono activado (sounddevice). Escuchando...")
                while self._running:
                    threshold = 300 # Ajustar según ruido ambiente
                    silence_chunks = 0
                    recording = []
                    is_recording = False
                    
                    while self._running:
                        try:
                            chunk = self.q.get(timeout=0.5)
                        except queue.Empty:
                            continue
                            
                        energy = np.abs(chunk).mean()
                        
                        if not is_recording:
                            if energy > threshold:
                                is_recording = True
                                recording.append(chunk)
                                silence_chunks = 0
                        else:
                            recording.append(chunk)
                            if energy < threshold:
                                silence_chunks += 1
                            else:
                                silence_chunks = 0
                                
                            if silence_chunks > 3: # ~1.5 segundos de silencio
                                break
                    
                    if recording and self._running:
                        audio_data = np.concatenate(recording)
                        audio = sr.AudioData(audio_data.tobytes(), self.samplerate, 2)
                        
                        try:
                            text = self.recognizer.recognize_google(audio, language="es-ES").lower()
                            print(f"🎤 [Reconocido]: '{text}'")
                            
                            if "cloe" in text or "chloe" in text:
                                command = text.replace("hey cloe", "").replace("hey chloe", "").replace("cloe", "").replace("chloe", "").strip()
                                if command.startswith(",") or command.startswith(":"):
                                    command = command[1:].strip()
                                if command:
                                    print(f"[Comando enviado a Cloe]: '{command}'")
                                    self.speech_detected.emit(command)
                                else:
                                    print("[Comando vacío tras palabra clave]")
                            else:
                                print("[Palabra clave 'Cloe' no detectada en la frase]")
                        except sr.UnknownValueError:
                            print("[No se entendió lo que dijiste]")
                        except sr.RequestError as e:
                            print(f"[Error de conexión con Google]: {e}")
                        except Exception as e:
                            print(f"[Error inesperado]: {e}")
                            
        except Exception as e:
            print(f"Error inicializando sounddevice: {e}")

    def stop(self):
        self._running = False
        self.wait()


# ── Personaje principal ────────────────────────────────────────────────────────
class CloePet(QWidget):
    SIZE = 110

    def __init__(self):
        super().__init__()
        self._drag_pos: QPoint | None = None
        self._face     = IDLE_FACES[0]
        self._face_idx = 0
        self._glow_r   = 0.0          # 0.0 → 1.0 para animación de glow
        self._glow_dir = 1
        self.messages: list[dict] = []
        self.tools:    list[dict] = []
        self.services: dict       = {}

        self._busy = False   # True mientras espera respuesta

        self.mic_enabled = "mic_on" in sys.argv
        if self.mic_enabled:
            self.voice_worker = VoiceWorker()
            self.voice_worker.speech_detected.connect(self._on_voice_input)
            self.voice_worker.start()

        self._setup_window()
        self._bubble = SpeechBubble()
        self._input  = InputPopup()
        self._input.submitted.connect(self._on_user_input)
        self._idle_timer  = QTimer(self)
        self._idle_timer.timeout.connect(self._next_face)
        self._idle_timer.start(3500)
        self._glow_timer  = QTimer(self)
        self._glow_timer.timeout.connect(self._tick_glow)
        self._glow_timer.start(50)
        self._solo_timer  = QTimer(self)
        self._solo_timer.setSingleShot(True)
        self._solo_timer.timeout.connect(self._hablar_sola)
        self._connect_backend()

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(self.SIZE, self.SIZE)

    # ── Pintar ───────────────────────────────────────────────────────────────
    def paintEvent(self, _):
        s = self.SIZE
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Glow exterior animado
        glow = QRadialGradient(s / 2, s / 2, s / 2)
        alpha = int(40 + 40 * self._glow_r)
        glow.setColorAt(0.55, QColor(130, 80, 220, alpha))
        glow.setColorAt(1.0,  QColor(80,  40, 160, 0))
        p.setBrush(glow)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(0, 0, s, s)

        # Cuerpo principal
        body = QRadialGradient(s / 2, s / 2, s * 0.4)
        body.setColorAt(0.0, QColor(55,  35,  90, 230))
        body.setColorAt(1.0, QColor(30,  18,  58, 230))
        p.setBrush(body)
        margin = 10
        p.drawEllipse(margin, margin, s - margin * 2, s - margin * 2)

        # Borde suave
        p.setPen(QColor(140, 100, 240, 120))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(margin, margin, s - margin * 2, s - margin * 2)

        # Cara
        p.setPen(QColor(220, 200, 255))
        font = QFont("Segoe UI", 13)
        font.setBold(True)
        p.setFont(font)
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._face)

    # ── Animaciones ──────────────────────────────────────────────────────────
    def _next_face(self):
        self._face_idx = (self._face_idx + 1) % len(IDLE_FACES)
        self._face = IDLE_FACES[self._face_idx]
        self.update()

    def _set_face(self, faces: list):
        import random
        self._face = random.choice(faces)
        self.update()

    def _tick_glow(self):
        self._glow_r += 0.04 * self._glow_dir
        if self._glow_r >= 1.0:
            self._glow_dir = -1
        elif self._glow_r <= 0.0:
            self._glow_dir = 1
        self.update()

    # ── Eventos de mouse ──────────────────────────────────────────────────────
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            moved = (event.globalPosition().toPoint() - self.frameGeometry().topLeft()) != self._drag_pos
            self._drag_pos = None
            if not moved:
                self._toggle_input()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self._drag_pos:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            # La burbuja sigue al pet en lugar de desaparecer
            if self._bubble.isVisible():
                self._bubble.reposition(self.geometry())
            if self._input.isVisible():
                self._input.reposition(self.geometry())

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background: #16162a; color: #e8e8f0; border: 1px solid #3d3d6b; border-radius: 8px; }
            QMenu::item:selected { background: #3d2d7a; border-radius: 4px; }
            QMenu::item { padding: 6px 20px; }
        """)
        chat_act = QAction("💬  Abrir chat", self)
        chat_act.triggered.connect(self._toggle_input)
        salir    = QAction("✕  Salir", self)
        salir.triggered.connect(self._quit_app)
        menu.addAction(chat_act)
        menu.addSeparator()
        menu.addAction(salir)
        menu.exec(event.globalPos())

    def _toggle_input(self):
        if self._input.isVisible():
            self._input.hide()
        else:
            self._bubble.hide_now()
            self._input.show_near(self.geometry())

    # ── Backend ───────────────────────────────────────────────────────────────
    def _connect_backend(self):
        class Loader(QThread):
            done = pyqtSignal(dict, list, list)
            def run(self_inner):
                services  = connect_services()
                client    = ollama.Client(host=OLLAMA_HOST)
                tools     = available_tool_names(services)
                modelfile = get_modelfile_system(client)
                hints     = build_tool_hints(services)
                system    = (modelfile + "\n\n" + hints).strip() if hints else modelfile
                msgs      = [{"role": "system", "content": system}] if system else []
                self_inner.done.emit(services, tools, msgs)

        self._loader = Loader()
        self._loader.done.connect(self._on_backend_ready)
        self._loader.start()

    def _on_backend_ready(self, services, tools, messages):
        self.services   = services
        self.tools      = tools
        self.messages   = messages
        self.client     = ollama.Client(host=OLLAMA_HOST)
        self.dispatcher = ToolDispatcher(services)
        # Saludo al arrancar
        hora    = datetime.now().strftime("%H:%M")
        trigger = f"Son las {hora}. Salúdame muy brevemente (máximo 1 oración) sin listas."
        self._run_cloe(trigger)
        # Primer timer de charla espontánea (entre 3 y 8 minutos)
        self._schedule_solo()

    def _schedule_solo(self):
        # Cada 3-10 minutos, Cloe habla sola
        delay_ms = random.randint(3 * 60_000, 10 * 60_000)
        self._solo_timer.start(delay_ms)

    def _hablar_sola(self):
        if self._busy or not hasattr(self, "client"):
            self._schedule_solo()
            return
        prompt = random.choice(SOLO_PROMPTS)
        self._run_cloe(prompt, solo=True)

    def _on_user_input(self, text: str):
        self._last_user_input = text
        self._bubble.hide_now()
        self._set_face(THINK_FACES)
        self._idle_timer.stop()
        self._run_cloe(text)

    def _run_cloe(self, text: str, solo: bool = False):
        if not hasattr(self, "client"):
            return
        self._busy = True
        self._worker = CloeWorker(self.client, self.messages, self.tools, self.dispatcher, text)
        self._worker.response_ready.connect(lambda r: self._on_response(r, solo=solo))
        self._worker.start()

    def _on_response(self, text: str, solo: bool = False):
        self._busy = False
        self._set_face(HAPPY_FACES)
        self._idle_timer.start(3500)
        hide_ms = 12000 if solo else 10000
        self._bubble.show_text(text, self.geometry(), auto_hide_ms=hide_ms)
        # Abre Spotify solo si el usuario habló de música
        last_input = getattr(self, "_last_user_input", "")
        if not solo and self.services.get("spotify") and is_music_context(last_input):
            for song, artist in detect_songs(text):
                play_track(self.services["spotify"], f"{song} {artist}")
        # Programar siguiente charla espontánea
        if solo:
            self._schedule_solo()

    def _on_voice_input(self, text: str):
        if self._input.isVisible():
            self._input.hide()
        self._on_user_input(text)

    def _quit_app(self):
        if hasattr(self, "voice_worker") and self.voice_worker.isRunning():
            self.voice_worker.stop()
        QApplication.quit()


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    pet = CloePet()
    screen = app.primaryScreen().geometry()
    pet.move(screen.width() - 150, screen.height() - 180)
    pet.show()
    sys.exit(app.exec())
