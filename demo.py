"""
Scripted demo conversation — your safety net for a loud hackathon room.

`CONVO` is the canned conversation (shared with the web HUD's "Run Demo" button).
Run this file directly for a terminal-only replay:

    python demo.py

If credentials.json is missing it uses a mock calendar automatically, so the
demo always runs even before Google is connected.
"""

# One line per "flush" (what the pipeline sees after a pause in speech).
CONVO = [
    "Yo what are you doing later? Nothing much. We should grab dinner at 7 tonight. Yeah let's do it.",
    "Wait can we actually push dinner to 8 instead? My class runs late. Yeah 8 works.",
    "Did you watch the game last night? Yeah it was insane, crazy ending.",
    "Hmm actually I'm not gonna be able to make dinner anymore, so sorry. No worries.",
    "Also let's get coffee tomorrow at 9am before the exam. Bet, see you then.",
]


def _use_mock_calendar_if_needed():
    """Patch calendar_tool with fakes when there's no credentials.json,
    so the demo runs without Google set up."""
    import os
    import calendar_tool

    if os.path.exists("credentials.json"):
        return False

    _n = [0]

    def _create(title, start_iso, duration_minutes=60, location=None, notes=None):
        _n[0] += 1
        return f"📅 created '{title}' at {start_iso} [id:mock{_n[0]}]"

    calendar_tool.create_event = _create
    calendar_tool.update_event = (
        lambda eid, start_iso=None, duration_minutes=None, **k: f"🔁 moved → {start_iso}"
    )
    calendar_tool.delete_event = lambda eid: "🗑️ cancelled"
    return True


if __name__ == "__main__":
    import time

    mock = _use_mock_calendar_if_needed()
    import agent

    print("=" * 70)
    print("  GLASSES AGENT — scripted demo" + ("  (mock calendar)" if mock else "  (LIVE calendar)"))
    print("=" * 70)
    for line in CONVO:
        print(f"\n🗣  {line}")
        for r in (agent.process_transcript(line) or ["   (no action — chit-chat)"]):
            print(f"   → {r}")
        time.sleep(0.6)
    print("\n✅ demo complete")
