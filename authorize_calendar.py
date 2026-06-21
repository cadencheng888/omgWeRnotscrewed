"""
One-time Google Calendar authorization.

Run this once to grant access and cache token.json. After it succeeds, the main
server (server.py) detects token.json and switches calendar mode to LIVE, so
events are written to your real Google Calendar.

    python authorize_calendar.py

It opens a browser for the Google consent screen. If you previously saw an
'invalid_scope' error, that came from a stale token — this regenerates a fresh
one with the calendar.events scope.
"""

import datetime
import os

import calendar_tool


def main() -> None:
    # Force a clean re-auth so stale scopes can't cause invalid_scope.
    if os.path.exists("token.json"):
        os.remove("token.json")
        print("• removed stale token.json")

    print("• opening browser for Google consent…")
    # _credentials() runs the local OAuth flow and writes token.json.
    calendar_tool._credentials()
    print("✅ token.json created — calendar is now LIVE.")

    # Smoke test: create a throwaway event ~10 min out so you can confirm it
    # shows up on your real calendar, then we leave it for you to delete.
    start = (datetime.datetime.now() + datetime.timedelta(minutes=10)).replace(microsecond=0)
    result = calendar_tool.create_event(
        title="✅ Hearsay calendar test",
        start_iso=start.isoformat(),
        duration_minutes=15,
        notes="Created by authorize_calendar.py — safe to delete.",
    )
    print("• test event:", result)
    print("\nDone. Restart the server (./run.sh) and calendar will be LIVE.")


if __name__ == "__main__":
    main()
