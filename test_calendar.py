"""
Verify Google Calendar is connected.

    python test_calendar.py

The FIRST run opens a browser to authorize (this is the one-time OAuth step;
it caches token.json). It then creates a real test event ~1 hour from now so
you can confirm it shows up on your calendar, and tells you the link.

Needs credentials.json in this folder first — see the setup steps.
"""

import datetime
import os
import zoneinfo

import calendar_tool

if not os.path.exists("credentials.json"):
    raise SystemExit(
        "❌ credentials.json not found in this folder.\n"
        "   Download your OAuth 'Desktop app' client from Google Cloud Console,\n"
        "   rename it to credentials.json, and put it next to this script."
    )

tz = zoneinfo.ZoneInfo(calendar_tool.TZ_NAME)
start = (datetime.datetime.now(tz) + datetime.timedelta(hours=1)).replace(
    minute=0, second=0, microsecond=0
)
start_iso = start.isoformat()

print("Opening browser to authorize (first run only)…")
result = calendar_tool.create_event(
    title="✅ Glasses Agent test",
    start_iso=start_iso,
    duration_minutes=30,
    notes="If you can see this event, your Google Calendar connection works.",
)
print(result)
print("\n👉 Check your Google Calendar around", start.strftime("%-I:%M %p today"))
print("   (delete the test event whenever — or just leave it).")
