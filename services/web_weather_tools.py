"""
Módulo 4: Clima en Tiempo Real y Búsqueda Web en Vivo para Cloe (100% gratis, sin API keys).
- Clima actual y pronóstico diario vía Open-Meteo + geolocalización IP automática
- Búsqueda web en vivo y noticias actuales vía DuckDuckGo HTML + Google News RSS + Wikipedia ES
"""

from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Optional

_WMO_CODES_ES: dict[int, str] = {
    0: "Cielo despejado ☀️",
    1: "Mayormente despejado 🌤️",
    2: "Parcialmente nublado ⛅",
    3: "Nublado ☁️",
    45: "Niebla 🌫️",
    48: "Niebla con escarcha 🌫️",
    51: "Llovizna ligera 🌦️",
    53: "Llovizna moderada 🌦️",
    55: "Llovizna intensa 🌧️",
    61: "Lluvia ligera 🌧️",
    63: "Lluvia moderada 🌧️",
    65: "Lluvia fuerte 🌧️",
    71: "Nevada ligera ❄️",
    73: "Nevada moderada ❄️",
    75: "Nevada fuerte ❄️",
    80: "Chubascos ligeros 🌦️",
    81: "Chubascos moderados 🌧️",
    82: "Chubascos fuertes ⛈️",
    95: "Tormenta eléctrica ⛈️",
    96: "Tormenta con granizo ⛈️",
    99: "Tormenta fuerte con granizo ⛈️",
}

_CACHED_GEO: Optional[dict] = None


def _http_get_json(url: str, timeout: float = 5.0) -> Optional[dict]:
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) CloeAssistant/2.0",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="ignore"))
    except Exception:
        return None


def _detect_user_location() -> Optional[dict]:
    """Detecta la ciudad y coordenadas aproximadas del usuario por IP (cacheado en memoria)."""
    global _CACHED_GEO
    if _CACHED_GEO is not None:
        return _CACHED_GEO

    data = _http_get_json("https://ipwho.is/", timeout=4.0)
    if data and data.get("success") is not False and data.get("latitude") is not None:
        _CACHED_GEO = {
            "city": data.get("city") or "tu ubicación",
            "country": data.get("country") or "",
            "lat": float(data["latitude"]),
            "lon": float(data["longitude"]),
        }
        return _CACHED_GEO

    data2 = _http_get_json("https://ipapi.co/json/", timeout=4.0)
    if data2 and data2.get("latitude") is not None:
        _CACHED_GEO = {
            "city": data2.get("city") or "tu ubicación",
            "country": data2.get("country_name") or "",
            "lat": float(data2["latitude"]),
            "lon": float(data2["longitude"]),
        }
        return _CACHED_GEO

    return None


def _geocode_city(city_name: str) -> Optional[dict]:
    """Busca coordenadas de una ciudad usando Open-Meteo Geocoding API."""
    q = urllib.parse.quote(city_name.strip())
    url = f"https://geocoding-api.open-meteo.com/v1/search?name={q}&count=1&language=es&format=json"
    data = _http_get_json(url, timeout=4.5)
    if not data:
        return None
    results = data.get("results") or []
    if not results:
        return None
    r = results[0]
    return {
        "city": r.get("name") or city_name,
        "country": r.get("country") or "",
        "lat": float(r["latitude"]),
        "lon": float(r["longitude"]),
    }


def fetch_weather_report(city_query: Optional[str] = None) -> str:
    """Obtiene el clima en tiempo real y el pronóstico de hoy desde Open-Meteo."""
    loc = _geocode_city(city_query) if city_query else None
    if loc is None:
        loc = _detect_user_location()
    if loc is None:
        return "No pude detectar tu ubicación para consultar el clima."

    lat = loc["lat"]
    lon = loc["lon"]
    place = f"{loc['city']}, {loc['country']}".strip(", ")

    url = (
        f"https://api.open-meteo.com/v1/forecast?latitude={lat:.4f}&longitude={lon:.4f}"
        "&current=temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m"
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max"
        "&timezone=auto&forecast_days=1"
    )
    data = _http_get_json(url, timeout=5.5)
    if not data or "current" not in data:
        return f"No pude conectar con el servicio meteorológico para {place}."

    curr = data.get("current") or {}
    daily = data.get("daily") or {}

    temp = curr.get("temperature_2m", "?")
    feels = curr.get("apparent_temperature", temp)
    hum = curr.get("relative_humidity_2m", "?")
    wind = curr.get("wind_speed_10m", "?")
    wcode = int(curr.get("weather_code", 0) or 0)
    cond = _WMO_CODES_ES.get(wcode, "Condición variable")

    t_max_list = daily.get("temperature_2m_max") or []
    t_min_list = daily.get("temperature_2m_min") or []
    rain_prob_list = daily.get("precipitation_probability_max") or []

    t_max = t_max_list[0] if t_max_list else "?"
    t_min = t_min_list[0] if t_min_list else "?"
    rain_prob = rain_prob_list[0] if rain_prob_list else 0

    return (
        f"Clima actual en {place}:\n"
        f"- Estado: {cond}\n"
        f"- Temperatura actual: {temp}°C (sensación térmica de {feels}°C)\n"
        f"- Máxima y mínima de hoy: máx {t_max}°C / mín {t_min}°C\n"
        f"- Probabilidad de lluvia hoy: {rain_prob}%\n"
        f"- Humedad: {hum}% · Viento: {wind} km/h"
    )


def _search_google_news_rss(query: str, max_items: int = 4) -> list[str]:
    """Obtiene titulares recientes desde el RSS público de Google News en español."""
    q = urllib.parse.quote(query.strip() or "tecnología mundo")
    url = f"https://news.google.com/rss/search?q={q}&hl=es-419&gl=CL&ceid=CL:es-419"
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) CloeAssistant/2.0"},
        )
        with urllib.request.urlopen(req, timeout=5.5) as resp:
            xml_bytes = resp.read()
        root = ET.fromstring(xml_bytes)
        items: list[str] = []
        for item in root.findall(".//item")[:max_items]:
            title = (item.findtext("title") or "").strip()
            pub = (item.findtext("pubDate") or "").strip()
            if title:
                short_pub = " ".join(pub.split()[:4]) if pub else ""
                items.append(f"• {title}" + (f" ({short_pub})" if short_pub else ""))
        return items
    except Exception:
        return []


def _search_duckduckgo_html(query: str, max_results: int = 4) -> list[str]:
    """Busca fragmentos reales en DuckDuckGo HTML sin necesidad de API key."""
    try:
        body = urllib.parse.urlencode({"q": query, "kl": "wt-wt"}).encode("utf-8")
        req = urllib.request.Request(
            "https://html.duckduckgo.com/html/",
            data=body,
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept-Language": "es-ES,es;q=0.9,en;q=0.7",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=6.0) as resp:
            raw_html = resp.read().decode("utf-8", errors="ignore")

        snippets = re.findall(
            r'<a class="result__snippet"[^>]*>(.*?)</a>',
            raw_html,
            flags=re.DOTALL | re.IGNORECASE,
        )
        titles = re.findall(
            r'<a rel="nofollow" class="result__a"[^>]*>(.*?)</a>',
            raw_html,
            flags=re.DOTALL | re.IGNORECASE,
        )
        results: list[str] = []
        for idx, snip in enumerate(snippets[:max_results]):
            clean_snip = html.unescape(re.sub(r"<[^>]+>", "", snip)).strip()
            clean_title = (
                html.unescape(re.sub(r"<[^>]+>", "", titles[idx])).strip()
                if idx < len(titles)
                else ""
            )
            if clean_snip:
                if clean_title:
                    results.append(f"• {clean_title}: {clean_snip}")
                else:
                    results.append(f"• {clean_snip}")
        return results
    except Exception:
        return []


def fetch_web_search_summary(query: str, is_news: bool = False) -> str:
    """Combina búsqueda en vivo de DuckDuckGo y Google News RSS."""
    clean_q = (query or "").strip()
    if not clean_q:
        return ""

    blocks: list[str] = []
    if is_news:
        news = _search_google_news_rss(clean_q, max_items=4)
        if news:
            blocks.append("Titulares recientes en vivo:\n" + "\n".join(news))

    ddg = _search_duckduckgo_html(clean_q, max_results=3)
    if ddg:
        blocks.append("Resultados web en vivo:\n" + "\n".join(ddg))

    if not blocks and not is_news:
        news_fallback = _search_google_news_rss(clean_q, max_items=3)
        if news_fallback:
            blocks.append("Resultados recientes:\n" + "\n".join(news_fallback))

    return "\n\n".join(blocks).strip()


def handle_web_or_weather_intent(user_text: str) -> Optional[str]:
    """
    Detecta si el usuario pregunta por el clima actual o pide buscar información/noticias en vivo en internet.
    Devuelve el contexto verificado para inyectar en el turno del LLM.
    """
    raw = (user_text or "").strip()
    if not raw:
        return None
    low = raw.lower()

    # 1. Intención de Clima / Temperatura / Lluvia
    if re.search(
        r"\b(clima|tiempo hace|qué tiempo|que tiempo|temperatura afuera|temperatura actual|temperatura en|va a llover|lloverá|llovera|pronóstico|pronostico|hace frío|hace frio|hace calor)\b",
        low,
    ):
        city: Optional[str] = None
        m_city = re.search(
            r"\b(?:clima|tiempo|temperatura|pronóstico|pronostico|llover)\s+(?:en|de|para)\s+([a-záéíóúñü\s]{2,35}?)(?:\s+hoy|\s+ahora|\s*[?.!]|$)",
            low,
        )
        if m_city:
            cand = m_city.group(1).strip()
            if cand not in ("mi ciudad", "aquí", "aqui", "aca", "acá", "hoy", "ahora"):
                city = cand
        report = fetch_weather_report(city)
        return (
            f"[Datos meteorológicos en tiempo real obtenidos de internet]:\n{report}\n"
            "[Instrucción: Responde al usuario de forma cálida y natural con estos datos exactos del clima actual.]"
        )

    # 2. Intención de Noticias / Búsqueda Web en Vivo
    news_match = re.search(
        r"\b(noticias|últimas noticias|ultimas noticias|qué ha pasado con|que ha pasado con|qué pasó con|que paso con|novedades sobre)\b\s*(?:de|sobre|en|del|acerca de)?\s*(.*)",
        low,
    )
    if news_match:
        topic = news_match.group(2).strip(" ?.!") or "actualidad tecnología mundo"
        summary = fetch_web_search_summary(topic, is_news=True)
        if summary:
            return (
                f"[Información en tiempo real buscada en internet sobre '{topic}']:\n{summary}\n"
                "[Instrucción: Resume de forma conversacional y directa las noticias o datos más relevantes para el usuario.]"
            )

    search_match = re.search(
        r"\b(?:busca en internet|busca en la web|búscame en internet|buscame en internet|investiga en internet|busca información sobre|busca informacion sobre|búscame|buscame|averigua)\b\s+(?:sobre|acerca de|qué es|que es|quién es|quien es)?\s*(.+)",
        low,
    )
    if search_match:
        q_topic = search_match.group(1).strip(" ?.!")
        # Evitar colisión con música
        if q_topic and not any(k in q_topic for k in ("canción", "cancion", "spotify", "música", "musica")):
            summary = fetch_web_search_summary(q_topic, is_news=False)
            if summary:
                return (
                    f"[Resultados buscados en vivo en internet para '{q_topic}']:\n{summary}\n"
                    "[Instrucción: Responde a la consulta del usuario usando estos datos actuales encontrados en la web.]"
                )

    return None
