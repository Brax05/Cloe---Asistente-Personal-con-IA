import os
import webbrowser
import spotipy
from spotipy.oauth2 import SpotifyOAuth

SCOPES = " ".join([
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "playlist-read-private",
    "playlist-read-collaborative",
    "playlist-modify-public",
    "playlist-modify-private",
    "user-library-read",
])


def create_client() -> spotipy.Spotify:
    client_id = (os.getenv("SPOTIFY_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("SPOTIFY_CLIENT_SECRET") or "").strip()
    if (
        not client_id
        or not client_secret
        or client_id == "tu_client_id_aqui"
        or client_secret == "tu_client_secret_aqui"
    ):
        raise RuntimeError("Credenciales de Spotify no configuradas en .env")
    cache_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".cache")
    return spotipy.Spotify(auth_manager=SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI", "http://localhost:8888/callback"),
        scope=SCOPES,
        open_browser=False,
        cache_path=cache_file,
    ))


# ── Lectura ────────────────────────────────────────────────────────────────────

def get_current_track(sp: spotipy.Spotify) -> dict:
    data = sp.current_playback()
    if not data or not data.get("item"):
        return {"playing": False, "message": "No hay nada sonando ahora."}
    item = data["item"]
    return {
        "playing": data["is_playing"],
        "name": item["name"],
        "artist": item["artists"][0]["name"],
        "album": item["album"]["name"],
        "progress_ms": data["progress_ms"],
        "duration_ms": item["duration_ms"],
        "url": item["external_urls"]["spotify"],
        "uri": item["uri"],
    }


def get_all_playlists(sp: spotipy.Spotify) -> list[dict]:
    playlists = []
    results = sp.current_user_playlists(limit=50)
    while results:
        for p in results["items"]:
            playlists.append({"id": p["id"], "name": p["name"], "tracks": p["tracks"]["total"]})
        results = sp.next(results) if results.get("next") else None
    return playlists


_MOOD_GENRES = {
    "feliz":       (["pop", "latin", "dance"],         dict(target_valence=0.8, target_energy=0.8)),
    "alegre":      (["pop", "latin", "dance"],         dict(target_valence=0.8, target_energy=0.8)),
    "energia":     (["edm", "hip-hop", "latin"],       dict(target_energy=0.9, target_tempo=128)),
    "fiesta":      (["latin", "reggaeton", "dance"],   dict(target_valence=0.9, target_danceability=0.9)),
    "triste":      (["indie", "acoustic", "sad"],      dict(target_valence=0.2, target_energy=0.3)),
    "melancolico": (["indie", "acoustic"],             dict(target_valence=0.2, target_energy=0.3)),
    "chill":       (["chill", "acoustic", "ambient"],  dict(target_energy=0.3, target_tempo=90)),
    "relajar":     (["ambient", "acoustic", "sleep"],  dict(target_energy=0.2, target_tempo=80)),
    "concentrar":  (["study", "classical", "ambient"], dict(target_instrumentalness=0.7, target_energy=0.4)),
    "focus":       (["study", "classical", "ambient"], dict(target_instrumentalness=0.7, target_energy=0.4)),
    "romantico":   (["romance", "soul", "r-n-b"],      dict(target_valence=0.6, target_energy=0.4)),
    "morning":     (["pop", "acoustic", "latin"],      dict(target_energy=0.6, target_valence=0.7)),
    "noche":       (["chill", "r-n-b", "ambient"],     dict(target_energy=0.3, target_valence=0.5)),
}

def get_recommendations(sp: spotipy.Spotify, mood: str = "") -> dict:
    genres = ["pop", "latin"]
    audio_params: dict = {}
    search_term = mood or "música popular"

    if mood:
        mood_lower = mood.lower()
        for key, (g, params) in _MOOD_GENRES.items():
            if key in mood_lower:
                genres = g
                audio_params = params
                search_term = f"música {key}"
                break

    # Intentar API de recomendaciones sin abrir el navegador
    try:
        recs = sp.recommendations(seed_genres=genres, limit=10, **audio_params)
        tracks = [
            {
                "name": t["name"],
                "artist": t["artists"][0]["name"],
                "uri": t["uri"],
                "url": t["external_urls"]["spotify"],
            }
            for t in recs["tracks"]
        ]
        if tracks:
            return {"success": True, "method": "api", "tracks": tracks}
    except Exception:
        pass

    return {
        "success": False,
        "method": "none",
        "message": f"No se pudieron obtener recomendaciones de Spotify API para '{search_term}'.",
    }


# ── Control ────────────────────────────────────────────────────────────────────

def _active_device(sp: spotipy.Spotify) -> str | None:
    devices = sp.devices().get("devices", [])
    active = next((d for d in devices if d["is_active"]), None)
    return (active or devices[0])["id"] if (active or devices) else None


def pause_playback(sp: spotipy.Spotify) -> dict:
    try:
        sp.pause_playback()
        return {"success": True, "message": "Música pausada."}
    except Exception as e:
        return {"success": False, "error": str(e)}


def resume_playback(sp: spotipy.Spotify) -> dict:
    try:
        device_id = _active_device(sp)
        sp.start_playback(device_id=device_id)
        return {"success": True, "message": "Música reanudada."}
    except Exception as e:
        return {"success": False, "error": str(e)}


def next_track(sp: spotipy.Spotify) -> dict:
    try:
        sp.next_track()
        return {"success": True, "message": "Siguiente canción."}
    except Exception as e:
        return {"success": False, "error": str(e)}


def previous_track(sp: spotipy.Spotify) -> dict:
    try:
        sp.previous_track()
        return {"success": True, "message": "Canción anterior."}
    except Exception as e:
        return {"success": False, "error": str(e)}


def set_volume(sp: spotipy.Spotify, level: int) -> dict:
    level = max(0, min(100, level))
    try:
        device_id = _active_device(sp)
        sp.volume(level, device_id=device_id)
        return {"success": True, "message": f"Volumen ajustado a {level}%."}
    except Exception as e:
        return {"success": False, "error": str(e)}


def play_track(sp: spotipy.Spotify, query: str) -> dict:
    try:
        results = sp.search(q=query, limit=1, type="track")
        items = results["tracks"]["items"]
        if not items:
            return {"success": False, "message": f"No encontré '{query}' en Spotify."}

        track = items[0]
        info = {
            "name": track["name"],
            "artist": track["artists"][0]["name"],
            "url": track["external_urls"]["spotify"],
            "uri": track["uri"],
        }

        try:
            device_id = _active_device(sp)
            if device_id:
                sp.start_playback(device_id=device_id, uris=[track["uri"]])
                info.update({"success": True, "method": "playback"})
                return info
        except Exception:
            pass

        info.update({"success": False, "method": "no_active_device"})
        return info
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def add_to_queue(sp: spotipy.Spotify, query: str) -> dict:
    results = sp.search(q=query, limit=1, type="track")
    items = results["tracks"]["items"]
    if not items:
        return {"success": False, "error": f"No encontré '{query}'."}
    track = items[0]
    try:
        sp.add_to_queue(track["uri"])
        return {
            "success": True,
            "message": f"Añadido a la cola: {track['name']} — {track['artists'][0]['name']}",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Contexto para el sistema ───────────────────────────────────────────────────

def format_playlist_context(tracks: list[dict]) -> str:
    lines = [
        "PLAYLIST DEL USUARIO en Spotify — puedes recomendar estas canciones:",
        "Cuando menciones una canción usa EXACTAMENTE este formato: ♪ nombre - artista",
        "",
    ]
    for t in tracks:
        lines.append(f"♪ {t['name']} - {t['artist']}")
    return "\n".join(lines)


def get_playlist_tracks(sp: spotipy.Spotify, playlist_id: str = "") -> list[dict]:
    if not playlist_id:
        playlist_id = os.getenv("SPOTIFY_PLAYLIST_ID", "")
    if not playlist_id:
        return []
    tracks = []
    results = sp.playlist_tracks(playlist_id, fields="items(track(id,name,uri,artists,external_urls)),next")
    while results:
        for item in results["items"]:
            track = item.get("track")
            if track and track.get("id"):
                tracks.append({
                    "id": track["id"],
                    "name": track["name"],
                    "artist": track["artists"][0]["name"],
                    "uri": track["uri"],
                    "url": track["external_urls"]["spotify"],
                })
        results = sp.next(results) if results.get("next") else None
    return tracks
