import base64
from email.mime.text import MIMEText
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials


def get_gmail_service(creds: Credentials):
    return build("gmail", "v1", credentials=creds)


def get_unread_emails(service, limit: int = 5) -> dict:
    try:
        result = service.users().messages().list(
            userId="me", labelIds=["INBOX", "UNREAD"], maxResults=limit
        ).execute()
        messages = result.get("messages", [])
        if not messages:
            return {"success": True, "emails": "No tienes correos no leídos.", "count": 0}

        emails = []
        for msg in messages:
            data = service.users().messages().get(
                userId="me", id=msg["id"], format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            ).execute()
            headers = {h["name"]: h["value"] for h in data["payload"]["headers"]}
            emails.append({
                "from": headers.get("From", ""),
                "subject": headers.get("Subject", ""),
                "date": headers.get("Date", ""),
                "snippet": data.get("snippet", ""),
            })

        return {"success": True, "emails": _format_emails(emails), "count": len(emails)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def send_email(service, to: str, subject: str, body: str) -> dict:
    try:
        msg = MIMEText(body)
        msg["to"] = to
        msg["subject"] = subject
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return {"success": True, "message": f"Correo enviado a {to}."}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _format_emails(emails: list) -> str:
    lines = []
    for i, e in enumerate(emails, 1):
        sender = e["from"].split("<")[0].strip() or e["from"]
        lines.append(f"{i}. De: {sender[:40]}")
        lines.append(f"   Asunto: {e['subject']}")
        lines.append(f"   {e['snippet'][:120]}...")
        lines.append("")
    return "\n".join(lines).strip()
