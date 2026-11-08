#!/usr/bin/env python3
"""
Script interactivo para configurar y autorizar Spotify y Google (Gmail + Calendar) en Cloe.
"""

import os
import sys
import pickle
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"), override=True)


def check_and_auth_spotify():
    print("\n" + "═" * 58)
    print(" 🎵 CONFIGURACIÓN DE SPOTIFY")
    print("═" * 58)

    client_id = (os.getenv("SPOTIFY_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("SPOTIFY_CLIENT_SECRET") or "").strip()
    redirect_uri = os.getenv("SPOTIFY_REDIRECT_URI", "http://localhost:8888/callback").strip()

    if (
        not client_id
        or not client_secret
        or client_id == "tu_client_id_aqui"
        or client_secret == "tu_client_secret_aqui"
    ):
        print("❌ Faltan credenciales en tu archivo .env")
        print("\nPara obtenerlas gratis en 2 minutos:")
        print("  1. Entra a: https://developer.spotify.com/dashboard")
        print("  2. Inicia sesión con tu cuenta de Spotify y pulsa 'Create app'.")
        print("  3. Nombre: Cloe (o lo que gustes).")
        print(f"  4. Redirect URI: Coloca exactamente: {redirect_uri}")
        print("  5. Selecciona la casilla 'Web API' y pulsa Save.")
        print("  6. Ve a 'Settings', copia tu 'Client ID' y 'Client Secret' y colócalos en tu archivo .env:")
        print("     SPOTIFY_CLIENT_ID=tu_id")
        print("     SPOTIFY_CLIENT_SECRET=tu_secret")
        return False

    try:
        import spotipy
        from spotipy.oauth2 import SpotifyOAuth
        from services.spotify_tools import SCOPES

        print("Conectando con Spotify OAuth...")
        sp_oauth = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope=SCOPES,
            open_browser=True,
            cache_path=os.path.join(BASE_DIR, ".cache"),
        )

        sp = spotipy.Spotify(auth_manager=sp_oauth)
        user = sp.current_user()
        user_name = user.get("display_name", "Usuario")
        print(f"✅ ¡Conectado con éxito a Spotify como: {user_name}!")

        # Mostrar playlists disponibles
        playlists = sp.current_user_playlists(limit=5)
        items = playlists.get("items", [])
        if items:
            print(f"   Tus primeras {len(items)} playlists encontradas:")
            for p in items:
                print(f"   • {p['name']} (ID: {p['id']})")
            print("   👉 Puedes copiar el ID de tu playlist favorita en .env (SPOTIFY_PLAYLIST_ID=id)")
        return True
    except Exception as exc:
        print(f"⚠️ Error al conectar con Spotify: {exc}")
        return False


def check_and_auth_google():
    print("\n" + "═" * 58)
    print(" 📅 CONFIGURACIÓN DE GOOGLE (GMAIL Y CALENDAR)")
    print("═" * 58)

    creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")
    if not os.path.isabs(creds_path):
        creds_path = os.path.join(BASE_DIR, creds_path)

    token_path = os.getenv("GOOGLE_TOKEN_PATH", "token.pickle")
    if not os.path.isabs(token_path):
        token_path = os.path.join(BASE_DIR, token_path)

    if not os.path.exists(creds_path):
        print(f"❌ No se encontró el archivo '{os.path.basename(creds_path)}' en la carpeta de Cloe.")
        print("\nPara descargarlo gratis desde Google Cloud Console:")
        print("  1. Entra a: https://console.cloud.google.com")
        print("  2. Crea un proyecto (por ejemplo: 'Cloe Asistente').")
        print("  3. Ve a 'APIs y servicios' → 'Biblioteca' y HABILITA dos APIs:")
        print("     • Google Calendar API")
        print("     • Gmail API")
        print("  4. Ve a 'Pantalla de consentimiento de OAuth':")
        print("     • Tipo de usuario: Externo.")
        print("     • Completa nombre de app y tu email.")
        print("     • En 'Usuarios de prueba' (Test users), AGREGA TU PROPIO CORREO GMAIL.")
        print("  5. Ve a 'Credenciales' → 'Crear credenciales' → 'ID de cliente de OAuth':")
        print("     • Tipo de aplicación: 'App de escritorio' (Desktop app).")
        print("     • Pulsa Crear y luego 'Descargar JSON'.")
        print(f"  6. Renombra ese archivo descargado como 'credentials.json' y muévelo a:")
        print(f"     {BASE_DIR}/credentials.json")
        return False

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from services.google_auth import SCOPES
        from googleapiclient.discovery import build

        creds = None
        if os.path.exists(token_path):
            with open(token_path, "rb") as f:
                creds = pickle.load(f)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                print("Refrescando token existente de Google...")
                creds.refresh(Request())
            else:
                print("Abriendo el navegador para autorizar Calendar y Gmail...")
                flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
                creds = flow.run_local_server(port=0)

            with open(token_path, "wb") as f:
                pickle.dump(creds, f)

        # Probar servicios
        cal_svc = build("calendar", "v3", credentials=creds)
        cal_list = cal_svc.calendarList().list(maxResults=1).execute()
        gmail_svc = build("gmail", "v1", credentials=creds)
        profile = gmail_svc.users().getProfile(userId="me").execute()

        print(f"✅ ¡Conectado con éxito a Google!")
        print(f"   • Cuenta de Gmail: {profile.get('emailAddress')}")
        print(f"   • Google Calendar activo y listo para agendar/consultar eventos.")
        return True
    except Exception as exc:
        print(f"⚠️ Error al conectar con Google: {exc}")
        return False


def main():
    print("\n╔════════════════════════════════════════════════════════╗")
    print("║     🐾 ASISTENTE DE CONEXIÓN DE CUENTAS DE CLOE        ║")
    print("╚════════════════════════════════════════════════════════╝")
    print("Cloe ya tiene todo el código listo para gestionar tu Spotify,")
    print("tus playlists, leer/enviar correos de Gmail y tu agenda de Google.")
    print("Aquí verificamos y autorizamos tus accesos.")

    sp_ok = check_and_auth_spotify()
    goog_ok = check_and_auth_google()

    print("\n" + "═" * 58)
    print(" 📋 RESUMEN DE ESTADO")
    print("═" * 58)
    print(f"  • Spotify: {'✅ Conectado y Autorizado' if sp_ok else '⏳ Pendiente (Faltan claves en .env)'}")
    print(f"  • Google (Gmail + Calendar): {'✅ Conectado y Autorizado' if goog_ok else '⏳ Pendiente (Falta credentials.json)'}")
    print("═" * 58)

    if sp_ok and goog_ok:
        print("\n🎉 ¡Todo está 100% configurado! Ya puedes abrir Cloe (`./run_gui.sh`).")
    else:
        print("\n💡 Cuando tengas las claves o el archivo, vuelve a ejecutar:")
        print("   python conectar_cuentas.py")


if __name__ == "__main__":
    main()
