"""Limpieza de texto para que el TTS no lea kaomojis, markdown ni emojis."""

from __future__ import annotations

import re


# Kaomojis de gato encerrados en paréntesis, con sus modificadores pegados.
_PAREN_KAOMOJI = re.compile(
    r"[\(（][^()\n]{0,40}[=^ω･‥▽◡Д≧≦口ᆺミΦヮ][^()\n]{0,40}[\)）]"
    r"[\sノヽ丿ฅづψΣ♡وb✨☆♪~]*"
)

# Kaomojis sin paréntesis (gatos, estrellas, etc.).
_BARE_KAOMOJI = re.compile(
    r"(?:ฅ[^ \n]{0,40}ฅ|[/\\]?ᐠ[^ \n]{0,20}ᐟ[/\\]?|ψ[^ \n]{0,40}ψ"
    r"|[٩۶][^ \n]{0,40}[و۶]|ミ[^ \n]{0,20}ミ|\^[^ \n]{0,20}\^)"
)

# Símbolos decorativos que no aportan nada al habla.
_DECORATIVE = re.compile(r"[Σψ٩۶وノヽ丿ฅᐠᐟづ♡♪✨☆★•·]")
_EMOJI = re.compile(
    r"[\U0001F000-\U0001FAFF\u2600-\u27BF\u2190-\u21FF\u2B00-\u2BFF]"
)

_CODE_FENCE = re.compile(r"```[\s\S]*?```")
_UNCLOSED_CODE_FENCE = re.compile(r"```[\s\S]*$")
_INLINE_CODE = re.compile(r"`([^`]*)`")
_MD_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]+\)")
_HEADING = re.compile(r"(?m)^\s{0,3}#{1,6}\s*")
_BLOCKQUOTE = re.compile(r"(?m)^\s*>\s?")
_BULLET = re.compile(r"(?m)^\s*[-*+]\s+")
_NUMBERED = re.compile(r"(?m)^\s*\d+[.)]\s+")
_EMPHASIS = re.compile(r"[*_]{1,3}")
_HR = re.compile(r"(?m)^\s*[-*_]{3,}\s*$")
_MUSIC_LINE = re.compile(r"(?m)^\s*♪\s*([^-\n]+?)\s+-\s+([^-\n]+?)\s*$")

# Detecta líneas de código sueltas (por si el modelo olvida abrir ```)
_RAW_CODE_LINE = re.compile(
    r"^\s*(?:"
    r"(?:def|class|import|from|return|if|elif|else|for|while|try|except|finally|with|async|await)\s+.+[:\(]?|"
    r"(?:const|let|var|function|export|interface|type|struct|enum|public|private|protected)\s+.+|"
    r"#include\s*[<\"].+|"
    r"(?:print|console\.log|System\.out\.println)\s*\(.*\)|"
    r"</?[a-zA-Z][a-zA-Z0-9_-]*(?:\s+[^>]*)?>|"
    r"[a-zA-Z_][a-zA-Z0-9_.]*\s*=\s*[^=\n]+|"
    r".*[{};]{1,2}\s*$"
    r")\s*$"
)


def _strip_code_lines(text: str) -> str:
    """Elimina líneas que son código fuente puro para que el TTS solo lea la explicación."""
    out_lines: list[str] = []
    for line in text.splitlines():
        if _RAW_CODE_LINE.match(line):
            continue
        # Ignorar líneas con alta densidad de símbolos de programación
        sym_count = sum(1 for ch in line if ch in "{}[]();=<>_+/\\|&^%$#@~`")
        if len(line.strip()) > 6 and sym_count >= 4:
            continue
        out_lines.append(line)
    return "\n".join(out_lines)


def clean_for_speech(text: str) -> str:
    """Devuelve una versión hablable de una respuesta de Cloe (sin código, markdown ni kaomojis)."""
    if not text:
        return ""

    # Canciones: "♪ canción - artista" → "canción, de artista"
    text = _MUSIC_LINE.sub(r"\1, de \2", text)

    # Bloques de código cerrados y abiertos (nunca leer código en voz alta)
    text = _CODE_FENCE.sub(" ", text)
    text = _UNCLOSED_CODE_FENCE.sub(" ", text)
    text = _strip_code_lines(text)

    # Si un código inline parece una expresión de código (con paréntesis, puntos, guiones bajos o símbolos), omitirlo
    def _clean_inline(m: re.Match) -> str:
        inner = m.group(1).strip()
        if any(ch in inner for ch in "(){}[];=<>_/\\") or len(inner) > 28:
            return " "
        return inner

    text = _INLINE_CODE.sub(_clean_inline, text)
    text = _MD_LINK.sub(r"\1", text)
    text = _HR.sub(" ", text)
    text = _HEADING.sub("", text)
    text = _BLOCKQUOTE.sub("", text)
    text = _BULLET.sub("", text)
    text = _NUMBERED.sub("", text)
    text = _EMPHASIS.sub("", text)

    # Kaomojis y decoración.
    text = _PAREN_KAOMOJI.sub(" ", text)
    text = _BARE_KAOMOJI.sub(" ", text)
    text = _DECORATIVE.sub("", text)
    text = _EMOJI.sub("", text)

    # El símbolo de gato dormido sin paréntesis: "(= -.zzZ"
    text = re.sub(r"\(=\s*-\.?\s*zzZ", " ", text, flags=re.IGNORECASE)

    # Normalizar risas y muletillas de texto que suenan robóticas en TTS
    text = re.sub(r"\b(?:ja){2,}j?\b", "jaja", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:je){2,}j?\b", "jeje", text, flags=re.IGNORECASE)
    text = re.sub(r"\bw{3,}\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bpfff+\b", "uf", text, flags=re.IGNORECASE)
    text = re.sub(r"\bzz+z*\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"[!?]{2,}", lambda m: "!" if "!" in m.group(0) else "?", text)
    text = re.sub(r"\.{2,}", ". ", text)

    # Espacios y saltos razonables para que el TTS respire.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def truncate_for_speech(text: str, max_chars: int = 1500) -> str:
    """Recorta en un límite de frase para no leer respuestas eternas."""
    text = text.strip()
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    # Busca el último cierre de frase dentro del límite.
    for mark in (". ", "! ", "? ", "\n"):
        pos = cut.rfind(mark)
        if pos > max_chars * 0.5:
            return cut[: pos + 1].strip()
    return cut.rstrip() + "..."


def split_for_speech(text: str, max_chars: int = 240) -> list[str]:
    """Parte un texto en frases naturales para sintetizar y reproducir sin latencia."""
    text = clean_for_speech(text)
    if not text:
        return []
    pieces: list[str] = []
    current = ""
    # Separar por fin de oración o salto de línea
    for part in re.split(r"(?<=[.!?…])\s+|\n+", text):
        part = part.strip()
        if not part:
            continue
        if current and len(current) + 1 + len(part) > max_chars:
            pieces.append(current.strip())
            current = part
        else:
            current = f"{current} {part}".strip() if current else part
            # Si la primera frase ya tiene tamaño hablable, emitirla rápido
            if not pieces and len(current) >= 35 and current[-1] in ".!?…":
                pieces.append(current.strip())
                current = ""
    if current:
        pieces.append(current.strip())
    return pieces


def pop_streaming_sentence(buffer: str, first_chunk: bool = False) -> tuple[str | None, str]:
    """Extrae la primera frase lista de un buffer en streaming para hablar al instante.

    Ignora por completo los bloques de código ```...``` (tanto cerrados como mientras se están
    generando en vivo) para que la voz solo lea la explicación y nunca las líneas de código.
    """
    if not buffer:
        return None, ""

    # 1. Eliminar cualquier bloque de código ```...``` que ya se haya cerrado en el buffer
    buffer = _CODE_FENCE.sub(" ", buffer)

    # 2. Si hay un bloque ``` abierto (en pleno streaming de código):
    if "```" in buffer:
        fence_idx = buffer.find("```")
        before_fence = buffer[:fence_idx].strip()
        rest_from_fence = buffer[fence_idx:]
        # Si había una explicación antes de abrir el bloque de código, hablarla primero
        if before_fence and clean_for_speech(before_fence):
            return before_fence, rest_from_fence
        # Mientras el bloque ``` siga abierto esperando su cierre, NO emitir nada al TTS
        return None, rest_from_fence

    # Ignorar si parece que se está abriendo un JSON de tool call inline
    stripped = buffer.lstrip()
    if stripped.startswith("{"):
        return None, buffer

    min_len = 18 if first_chunk else 32
    pattern = r"([.!?…]|\n)" if not first_chunk else r"([.!?…:;]|\n|,\s)"
    for match in re.finditer(pattern, buffer):
        end_idx = match.end()
        candidate = buffer[:end_idx].strip()
        cleaned = clean_for_speech(candidate)
        if len(cleaned) >= min_len:
            return candidate, buffer[end_idx:]

    if len(buffer) > 180:
        space_idx = buffer.rfind(" ", 0, 160)
        if space_idx > 40:
            candidate = buffer[:space_idx].strip()
            if clean_for_speech(candidate):
                return candidate, buffer[space_idx + 1:]

    return None, buffer

