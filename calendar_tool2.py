"""
Google Calendar + Google Tasks integration (the "external programs").

Auth uses Google's OAuth desktop flow:
  1. Create a Google Cloud project, enable the Google Calendar API and Tasks API.
  2. Create an OAuth client ID of type "Desktop app".
  3. Download it as credentials.json into this folder.
First run opens a browser to grant access; the token is cached in token.json.
"""

import datetime
import os
import zoneinfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
]
TZ_NAME = os.environ.get("LOCAL_TIMEZONE", "America/Los_Angeles")


def _credentials() -> Credentials:
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as f:
            f.write(creds.to_json())
    return creds


def create_event(title, start_iso, duration_minutes=60, location=None, notes=None) -> str:
    service = build("calendar", "v3", credentials=_credentials())

    start = datetime.datetime.fromisoformat(start_iso)
    end = start + datetime.timedelta(minutes=duration_minutes)

    body = {
        "summary": title,
        "start": {"dateTime": start.isoformat(), "timeZone": TZ_NAME},
        "end": {"dateTime": end.isoformat(), "timeZone": TZ_NAME},
    }
    if location:
        body["location"] = location
    if notes:
        body["description"] = notes

    event = service.events().insert(calendarId="primary", body=body).execute()
    # Append the real event id (in [id:...]) so the agent can cancel by the
    # actual id later — NOT the htmlLink's `eid`, which is base64(id+calendarId)
    # and is rejected by events().delete().
    return (
        f"📅 Calendar event created: '{title}' at {start_iso} -> "
        f"{event.get('htmlLink')} [id:{event['id']}]"
    )


def delete_event(event_id: str) -> str:
    service = build("calendar", "v3", credentials=_credentials())
    service.events().delete(calendarId="primary", eventId=event_id).execute()
    return f"🗑️  Calendar event deleted (id {event_id})"


def update_event(event_id, start_iso=None, duration_minutes=None,
                 location=None, notes=None) -> str:
    """Move/modify an existing event. If start_iso is given and
    duration_minutes is not, the original duration is preserved."""
    service = build("calendar", "v3", credentials=_credentials())
    event = service.events().get(calendarId="primary", eventId=event_id).execute()

    if start_iso:
        start = datetime.datetime.fromisoformat(start_iso)
        if duration_minutes is None:
            # Preserve the original duration when only the start moves.
            try:
                old_start = datetime.datetime.fromisoformat(event["start"]["dateTime"])
                old_end = datetime.datetime.fromisoformat(event["end"]["dateTime"])
                duration_minutes = int((old_end - old_start).total_seconds() // 60) or 60
            except (KeyError, ValueError):
                duration_minutes = 60
        end = start + datetime.timedelta(minutes=duration_minutes)
        event["start"] = {"dateTime": start.isoformat(), "timeZone": TZ_NAME}
        event["end"] = {"dateTime": end.isoformat(), "timeZone": TZ_NAME}
    elif duration_minutes is not None:
        start = datetime.datetime.fromisoformat(event["start"]["dateTime"])
        end = start + datetime.timedelta(minutes=duration_minutes)
        event["end"] = {"dateTime": end.isoformat(), "timeZone": TZ_NAME}

    if location is not None:
        event["location"] = location
    if notes is not None:
        event["description"] = notes

    updated = service.events().update(
        calendarId="primary", eventId=event_id, body=event
    ).execute()
    title = updated.get("summary", "event")
    new_when = updated.get("start", {}).get("dateTime", start_iso)
    return f"🔁 Rescheduled '{title}' to {new_when}"


def create_task(title, due_iso=None) -> str:
    service = build("tasks", "v1", credentials=_credentials())
    body = {"title": title}
    if due_iso:
        # Tasks API wants RFC3339 UTC ("Z").
        due = datetime.datetime.fromisoformat(due_iso).astimezone(zoneinfo.ZoneInfo("UTC"))
        body["due"] = due.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    task = service.tasks().insert(tasklist="@default", body=body).execute()
    return f"☑️  Task created: '{title}' (id {task.get('id')})"
