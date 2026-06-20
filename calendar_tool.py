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
    "https://www.googleapis.com/auth/tasks",
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
    return f"📅 Calendar event created: '{title}' at {start_iso} -> {event.get('htmlLink')}"


def create_task(title, due_iso=None) -> str:
    service = build("tasks", "v1", credentials=_credentials())
    body = {"title": title}
    if due_iso:
        # Tasks API wants RFC3339 UTC ("Z").
        due = datetime.datetime.fromisoformat(due_iso).astimezone(zoneinfo.ZoneInfo("UTC"))
        body["due"] = due.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    task = service.tasks().insert(tasklist="@default", body=body).execute()
    return f"☑️  Task created: '{title}' (id {task.get('id')})"
