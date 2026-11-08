import os
import pickle
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]


def get_google_credentials() -> Credentials:
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")
    if not os.path.isabs(creds_path):
        creds_path = os.path.join(base_dir, creds_path)

    token_path = os.getenv("GOOGLE_TOKEN_PATH", "token.pickle")
    if not os.path.isabs(token_path):
        token_path = os.path.join(base_dir, token_path)

    creds = None
    if os.path.exists(token_path):
        with open(token_path, "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(creds_path):
                raise FileNotFoundError(
                    f"No se encontró {creds_path}\n"
                    "Descárgalo desde: https://console.cloud.google.com\n"
                    "→ APIs & Services → Credentials → Create → OAuth 2.0 Client (Desktop app)"
                )
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "wb") as f:
            pickle.dump(creds, f)

    return creds
