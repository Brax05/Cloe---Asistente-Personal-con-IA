import os
from datetime import datetime, timedelta
from dateutil import parser as dateparser
import pytz
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials


def _tz() -> pytz.BaseTzInfo:
    return pytz.timezone(os.getenv("TIMEZONE", "America/Mexico_City"))


def get_calendar_service(creds: Credentials):
    return build("calendar", "v3", credentials=creds)


def get_today_events(service) -> dict:
    tz = _tz()
    now = datetime.now(tz)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = now.replace(hour=23, minute=59, second=59, microsecond=0)
    try:
        result = service.events().list(
            calendarId="primary",
            timeMin=start.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        events = result.get("items", [])
        return {"success": True, "events": _format_events(events), "count": len(events)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_upcoming_events(service, days: int = 7) -> dict:
    tz = _tz()
    now = datetime.now(tz)
    end = now + timedelta(days=days)
    try:
        result = service.events().list(
            calendarId="primary",
            timeMin=now.isoformat(),
            timeMax=end.isoformat(),
            maxResults=15,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        events = result.get("items", [])
        return {"success": True, "events": _format_events(events), "count": len(events)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def create_event(service, title: str, date_str: str, duration_minutes: int = 60, description: str = "") -> dict:
    tz = _tz()
    try:
        start = dateparser.parse(date_str)
        if start is None:
            return {"success": False, "error": f"No pude interpretar la fecha: '{date_str}'"}
        if start.tzinfo is None:
            start = tz.localize(start)
        end = start + timedelta(minutes=duration_minutes)
        event_body = {
            "summary": title,
            "description": description,
            "start": {"dateTime": start.isoformat(), "timeZone": str(tz)},
            "end": {"dateTime": end.isoformat(), "timeZone": str(tz)},
        }
        created = service.events().insert(calendarId="primary", body=event_body).execute()
        return {
            "success": True,
            "message": f"Evento creado: '{title}' el {start.strftime('%d/%m/%Y a las %H:%M')}",
            "link": created.get("htmlLink", ""),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _format_events(events: list) -> str:
    if not events:
        return "No hay eventos."
    lines = []
    for e in events:
        raw = e["start"].get("dateTime", e["start"].get("date", ""))
        try:
            dt = dateparser.parse(raw)
            label = dt.strftime("%d/%m %H:%M") if "T" in raw else dt.strftime("%d/%m (todo el día)")
        except Exception:
            label = raw
        lines.append(f"• {label} — {e.get('summary', 'Sin título')}")
    return "\n".join(lines)
