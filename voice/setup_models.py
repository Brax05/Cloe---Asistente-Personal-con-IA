"""Descarga el motor Piper y una voz en español para Cloe.

Uso:
    python -m voice.setup_models            # Piper + voz (recomendado)
    python -m voice.setup_models --check    # solo verificar
    python -m voice.setup_models --whisper  # además pre-descarga Whisper

Los binarios y modelos se guardan en voice/vendor y voice/models, que están
fuera de git por su tamaño.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from .config import VOICE_DIR, VoiceConfig


PIPER_VERSION = "2023.11.14-2"
PIPER_RELEASE = f"https://github.com/rhasspy/piper/releases/download/{PIPER_VERSION}"

VOICES: dict[str, dict[str, str]] = {
    "es_MX-claude-high": {
        "path": "es/es_MX/claude/high/es_MX-claude-high",
        "label": "es_MX · claude · high (femenina, natural)",
        "license": "dataset Apache-2.0",
    },
    "es_MX-ald-medium": {
        "path": "es/es_MX/ald/medium/es_MX-ald-medium",
        "label": "es_MX · ald · medium (femenina)",
        "license": "dataset Unlicense (dominio público)",
    },
    "es_ES-davefx-medium": {
        "path": "es/es_ES/davefx/medium/es_ES-davefx-medium",
        "label": "es_ES · davefx · medium (masculina)",
        "license": "ver MODEL_CARD",
    },
    "es_ES-sharvard-medium": {
        "path": "es/es_ES/sharvard/medium/es_ES-sharvard-medium",
        "label": "es_ES · sharvard · medium (2 voces)",
        "license": "ver MODEL_CARD",
    },
    "es_AR-daniela-high": {
        "path": "es/es_AR/daniela/high/es_AR-daniela-high",
        "label": "es_AR · daniela · high (femenina, rioplatense)",
        "license": "ver MODEL_CARD",
    },
}

DEFAULT_VOICE = "es_MX-claude-high"


def _piper_asset() -> tuple[str, str]:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "linux":
        if machine in {"x86_64", "amd64"}:
            return "piper_linux_x86_64.tar.gz", "tar"
        if machine in {"aarch64", "arm64"}:
            return "piper_linux_aarch64.tar.gz", "tar"
    elif system == "darwin":
        if machine in {"arm64", "aarch64"}:
            return "piper_macos_aarch64.tar.gz", "tar"
        return "piper_macos_x64.tar.gz", "tar"
    elif system == "windows":
        return "piper_windows_amd64.zip", "zip"
    raise SystemExit(
        f"Plataforma no soportada por este instalador: {system}/{machine}.\n"
        "Descarga Piper manualmente desde https://github.com/rhasspy/piper/releases"
    )


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    print(f"  ↓ {url}")
    try:
        with urllib.request.urlopen(url, timeout=120) as response:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            with open(tmp, "wb") as out:
                while True:
                    chunk = response.read(1024 * 256)
                    if not chunk:
                        break
                    out.write(chunk)
                    done += len(chunk)
                    if total:
                        pct = done * 100 / total
                        print(f"\r    {pct:5.1f}% ({done/1_048_576:.1f} MB)", end="")
        print()
        tmp.replace(dest)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def _safe_extract_tar(archive: Path, dest: Path) -> None:
    dest = dest.resolve()
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            target = (dest / member.name).resolve()
            if not str(target).startswith(str(dest)):
                raise SystemExit(f"Archivo inseguro en el tar: {member.name}")
        tar.extractall(dest)


def _safe_extract_zip(archive: Path, dest: Path) -> None:
    dest = dest.resolve()
    with zipfile.ZipFile(archive) as zf:
        for member in zf.namelist():
            target = (dest / member).resolve()
            if not str(target).startswith(str(dest)):
                raise SystemExit(f"Archivo inseguro en el zip: {member}")
        zf.extractall(dest)


def ensure_piper(force: bool = False) -> Path:
    config = VoiceConfig.from_env()
    piper_dir = config.piper_bin.parent
    binary = config.piper_bin
    if binary.exists() and not force:
        print(f"  ✓ Piper ya está en {binary}")
        return binary

    asset, kind = _piper_asset()
    print(f"Instalando Piper {PIPER_VERSION} ({asset})...")
    piper_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cloe_piper_") as tmp:
        archive = Path(tmp) / asset
        _download(f"{PIPER_RELEASE}/{asset}", archive)
        if kind == "tar":
            _safe_extract_tar(archive, piper_dir.parent)
        else:
            _safe_extract_zip(archive, piper_dir.parent)

    if not binary.exists():
        # Algunos empaquetados extraen en una carpeta con otro nombre.
        candidates = list(piper_dir.parent.rglob("piper"))
        candidates = [c for c in candidates if c.is_file()]
        if candidates:
            binary.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(candidates[0], binary)
        else:
            raise SystemExit("No encontré el ejecutable de Piper tras extraer el paquete.")

    if os.name != "nt":
        binary.chmod(binary.stat().st_mode | 0o111)
    print(f"  ✓ Piper instalado en {binary}")
    return binary


def ensure_voice(voice: str = DEFAULT_VOICE, force: bool = False) -> Path:
    if voice not in VOICES:
        raise SystemExit(
            f"Voz desconocida: {voice}\nVoces disponibles:\n  "
            + "\n  ".join(f"{k}: {v['label']}" for k, v in VOICES.items())
        )
    config = VoiceConfig.from_env()
    model = config.piper_model
    config_file = config.piper_config
    if config.piper_model.stem != voice:
        # Instalar una voz distinta a la configurada: su .json va junto al .onnx.
        model = config.piper_model.parent / f"{voice}.onnx"
        config_file = model.with_name(model.name + ".json")
    if model.exists() and config_file.exists() and not force:
        print(f"  ✓ Voz ya instalada en {model}")
        return model

    info = VOICES[voice]
    base = "https://huggingface.co/rhasspy/piper-voices/resolve/main/" + info["path"]
    print(f"Descargando voz {voice} ({info['label']})...")
    _download(base + ".onnx", model)
    _download(base + ".onnx.json", config_file)
    print(f"  ✓ Voz instalada: {model}")
    if info.get("license"):
        print(f"  · Licencia de la voz: {info['license']}")
    if model != config.piper_model or config_file != config.piper_config:
        print("  · Para usarla, define en tu .env:")
        print(f"      CLOE_PIPER_VOICE={voice}")
        print("    o bien:")
        print(f"      CLOE_PIPER_MODEL={model}")
        print(f"      CLOE_PIPER_CONFIG={config_file}")
    return model


def ensure_kokoro(force: bool = False) -> None:
    """Descarga los archivos de Kokoro (ONNX) si no están presentes."""
    config = VoiceConfig.from_env()
    model = config.kokoro_model
    voices = config.kokoro_voices
    if model.exists() and voices.exists() and not force:
        print(f"  ✓ Kokoro ya instalado en {model.parent}")
        return
    model.parent.mkdir(parents=True, exist_ok=True)
    base = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
    print("Descargando Kokoro (modelo + voces, ~340 MB)...")
    _download(f"{base}/kokoro-v1.0.onnx", model)
    _download(f"{base}/voices-v1.0.bin", voices)
    print(f"  ✓ Kokoro instalado en {model.parent}")


def ensure_whisper() -> None:
    config = VoiceConfig.from_env()
    print(f"Pre-descargando Whisper '{config.stt_model}'...")
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise SystemExit(
            "Falta faster-whisper. Instala las dependencias:\n"
            "  pip install -r requirements-voice.txt"
        )
    config.stt_download_root.mkdir(parents=True, exist_ok=True)
    model = WhisperModel(
        config.stt_model,
        device="cpu",
        compute_type="int8",
        download_root=str(config.stt_download_root),
    )
    del model
    print(f"  ✓ Whisper listo en {config.stt_download_root}")


def check() -> int:
    config = VoiceConfig.from_env()
    ok = True
    print("Estado de la voz de Cloe:")
    for label, path in (
        ("Piper (binario)", config.piper_bin),
        ("Voz .onnx", config.piper_model),
        ("Voz .json", config.piper_config),
    ):
        exists = path.exists()
        print(f"  {'✓' if exists else '✗'} {label}: {path}")
        ok = ok and exists

    print(f"  · STT: {config.stt_provider} / {config.stt_model} / {config.stt_device}")
    print(f"  · TTS: {config.tts_provider} / {config.tts_engine}")

    try:
        import faster_whisper  # noqa: F401
        print("  ✓ faster-whisper instalado")
    except ImportError:
        print("  ✗ faster-whisper no instalado (pip install -r requirements-voice.txt)")
        ok = False

    try:
        import kokoro_onnx  # noqa: F401
        cfg2 = VoiceConfig.from_env()
        kokoro_ok = cfg2.kokoro_model.exists() and cfg2.kokoro_voices.exists()
        if kokoro_ok:
            print(f"  ✓ Kokoro instalado ({cfg2.kokoro_voice})")
        else:
            print("  · Kokoro no descargado (python -m voice.setup_models --kokoro)")
    except ImportError:
        print("  · kokoro-onnx no instalado (opcional)")

    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Instala los modelos de voz de Cloe")
    parser.add_argument("--check", action="store_true", help="solo verificar")
    parser.add_argument("--whisper", action="store_true", help="pre-descargar Whisper")
    parser.add_argument("--kokoro", action="store_true", help="descargar Kokoro (TTS neural)")
    parser.add_argument("--voice", default=os.getenv("CLOE_PIPER_VOICE", DEFAULT_VOICE),
                        choices=sorted(VOICES), help="voz de Piper a instalar")
    parser.add_argument("--force", action="store_true", help="volver a descargar")
    args = parser.parse_args(argv)

    if args.check:
        return check()

    ensure_piper(force=args.force)
    ensure_voice(args.voice, force=args.force)
    if args.whisper:
        ensure_whisper()
    if args.kokoro:
        ensure_kokoro(force=args.force)
    print("\nVoz lista. Prueba el pipeline con:")
    print("  python -m voice.selftest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
