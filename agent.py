"""
Claude intent extraction.

Takes a window of conversation transcript and decides whether anything
actionable was said (a plan, an appointment, a to-do). If so, Claude calls one
of the tools below and we execute it.

This is the extensibility point: to support a new external program, add a tool
definition here + a handler in `execute_tool`. Claude figures out when to use it.
"""

import datetime
import os
import time
import zoneinfo

from anthropic import Anthropic
from dotenv import load_dotenv

import calendar_tool

load_dotenv()

TZ_NAME = os.environ.get("LOCAL_TIMEZONE", "America/Los_Angeles")
client = Anthropic()  # reads ANTHROPIC_API_KEY from env

# Tracks recently created events for dedup and cancellation.
# Each entry: {"event_id": str, "title": str, "start_iso": str, "created_at": float}
_recent_events: list[dict] = []
DEDUP_WINDOW_SECONDS = 300  # ignore reconfirmations within 5 minutes

# Titles that are too generic unless the transcript/tool input really supports them.
GENERIC_EVENT_TITLES = {"meeting", "event", "plan", "calendar event", "appointment"}

EVENT_TITLE_MAP = {
    "lunch": "Lunch",
    "dinner": "Dinner",
    "breakfast": "Breakfast",
    "coffee": "Coffee",
    "boba": "Boba",
    "drinks": "Drinks",
    "call": "Call",
    "class": "Class",
    "study": "Study Session",
    "study_session": "Study Session",
    "workout": "Workout",
    "practice": "Practice",
    "party": "Party",
    "movie": "Movie",
    "appointment": "Appointment",
    "errand": "Errand",
    "meeting": "Meeting",
    "social": "Hangout",
    "other": "Event",
}


def _event_key(title: str, start_iso: str) -> str:
    """Normalized key for dedup comparison."""
    # Truncate to the hour so minor time variations ("6pm" vs "18:00") still match.
    try:
        dt = datetime.datetime.fromisoformat(start_iso)
        time_bucket = dt.strftime("%Y-%m-%dT%H")
    except ValueError:
        time_bucket = start_iso[:13]
    return f"{title.strip().lower()}|{time_bucket}"


def _clean_event_type(event_type: str | None) -> str:
    """Normalize Claude's event_type into our known categories."""
    if not event_type:
        return "other"
    normalized = event_type.strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "meal": "other",
        "hangout": "social",
        "hang_out": "social",
        "study_session": "study_session",
        "gym": "workout",
        "phone_call": "call",
        "video_call": "call",
    }
    return aliases.get(normalized, normalized if normalized in EVENT_TITLE_MAP else "other")


def _specific_title_from_args(args: dict) -> str:
    """Return a specific title and prevent accidental 'Meeting' overuse.

    Claude is required to send event_type. If it sends a generic title such as
    'Meeting' but event_type is lunch/dinner/coffee/etc., trust event_type.
    """
    raw_title = str(args.get("title") or "").strip()
    event_type = _clean_event_type(args.get("event_type"))
    default_title = EVENT_TITLE_MAP.get(event_type, "Event")

    # If Claude gave no title or a generic title, derive from event_type.
    if not raw_title or raw_title.lower() in GENERIC_EVENT_TITLES:
        title = default_title
    else:
        title = raw_title

    # Hard guard: never title food/social/call plans as Meeting unless event_type is meeting.
    if title.strip().lower() == "meeting" and event_type != "meeting":
        title = default_title

    participants = args.get("participants") or []
    if isinstance(participants, str):
        participants = [participants]
    participants = [p.strip() for p in participants if isinstance(p, str) and p.strip()]

    # Add one participant to the title when it sounds natural and is not already included.
    if participants and " with " not in title.lower():
        person = participants[0]
        if person.lower() not in title.lower() and title in EVENT_TITLE_MAP.values():
            title = f"{title} with {person}"

    return title


# Tool schemas Claude can choose to call. Keep descriptions concrete — Claude
# uses them to decide when each applies.
TOOLS = [
    {
        "name": "create_calendar_event",
        "description": (
            "Create a Google Calendar event when people agree on a real-world plan "
            "with a specific date/time. Use a SPECIFIC activity title. Do not use "
            "'Meeting' unless the plan is actually a meeting/sync/discussion. For "
            "food plans use Lunch, Dinner, Breakfast, Coffee, Boba, or Drinks. For "
            "'call me at 6', use Call."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": (
                        "Specific activity title, e.g. 'Lunch', 'Dinner with Alex', "
                        "'Coffee', 'Call with Mom', 'Study Session'. Avoid 'Meeting' "
                        "unless the transcript explicitly indicates a meeting."
                    ),
                },
                "event_type": {
                    "type": "string",
                    "enum": [
                        "lunch",
                        "dinner",
                        "breakfast",
                        "coffee",
                        "boba",
                        "drinks",
                        "call",
                        "class",
                        "meeting",
                        "study",
                        "study_session",
                        "workout",
                        "practice",
                        "party",
                        "movie",
                        "appointment",
                        "errand",
                        "social",
                        "other",
                    ],
                    "description": (
                        "The real-world activity type. This should match the transcript; "
                        "do not choose 'meeting' for lunch/dinner/coffee/social plans."
                    ),
                },
                "start_iso": {
                    "type": "string",
                    "description": "Start time in ISO 8601 with offset, e.g. 2026-06-20T18:00:00-07:00.",
                },
                "duration_minutes": {
                    "type": "integer",
                    "description": "Event length in minutes. Default 60 if unclear.",
                },
                "location": {"type": "string", "description": "Location if mentioned."},
                "participants": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "People involved if their names are mentioned or obvious.",
                },
                "notes": {"type": "string", "description": "Any extra context."},
            },
            "required": ["title", "event_type", "start_iso"],
        },
    },
    {
        "name": "cancel_last_event",
        "description": (
            "Cancel / delete the most recently created calendar event. Use this "
            "when ANY speaker retracts, rejects, or becomes unavailable for the "
            "plan that was just made. Examples: 'cancel that', 'never mind', "
            "'forget it', 'actually I am busy', 'I cannot make it', 'rain check', "
            "'sorry, that will not work for me', 'maybe another time'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "create_task",
        "description": (
            "Create a Google Task / to-do. Use for action items without a fixed "
            "calendar event time, e.g. 'remind me to buy milk', 'I need to email Sam'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "due_iso": {
                    "type": "string",
                    "description": "Optional due date/time in ISO 8601.",
                },
            },
            "required": ["title"],
        },
    },
]


def _now_context() -> str:
    now = datetime.datetime.now(zoneinfo.ZoneInfo(TZ_NAME))
    return now.strftime("%A, %Y-%m-%d %H:%M %Z")


def build_system_prompt() -> str:
    """The instructions that tell Claude how to decide on actions.

    Shared by process_transcript() and the test scripts so they stay in sync.
    """
    return f"""
You are an assistant embedded in smart glasses. You passively receive transcribed snippets of the wearer's real-world conversations and must detect actionable plans, events, reminders, and to-dos.

Resolve relative dates and times like "6pm", "tonight", "tomorrow", "next Friday", and "in 20 minutes" against the current time: {_now_context()} (timezone {TZ_NAME}).

You cannot ask the wearer follow-up questions. They are not in a chat and cannot reply. If a plan or to-do is clear enough to act on, call the appropriate tool immediately using the best information available. Missing minor details, such as exact location or attendee name, should not prevent action.

Before creating an event, classify the plan:
1. Is the wearer personally involved?
2. Is this a confirmed/accepted plan, a rejected plan, a cancellation, a reconfirmation, or vague/hypothetical talk?
3. What is the specific activity type?
4. What title should appear on the calendar?

EVENT TITLE RULES:
- Prefer the most specific real-world activity mentioned.
- Do NOT use "Meeting" unless the transcript explicitly indicates a meeting, sync, work meeting, discussion, appointment, or generic meetup with no better label.
- If the transcript says lunch, use title="Lunch" and event_type="lunch".
- If it says dinner, use title="Dinner" and event_type="dinner".
- If it says coffee, use title="Coffee" and event_type="coffee".
- If it says boba, use title="Boba" and event_type="boba".
- If it says call me / phone / FaceTime, use title="Call" and event_type="call".
- If it says study, homework, project work, or review session, use title="Study Session" and event_type="study" or "study_session".
- If a person's name is known, include it naturally: "Lunch with Alex", "Call with Mom".

When extracting an event, infer as many fields as possible:
- event_type: lunch, dinner, breakfast, coffee, boba, drinks, call, class, meeting, study, workout, practice, party, movie, appointment, errand, social, or other
- title: specific calendar title based on the event_type and known person/context
- start date and time
- duration, if implied
- location, if mentioned
- participants, if mentioned
- notes with any useful context

ACTION RULES:
1. Create an event only when the wearer appears to have a real plan with a clear enough time/date.
2. Create a reminder or to-do only when someone clearly asks the wearer to do something, or the wearer says they need to do something.
3. If the transcript contains a clear time/date and clear commitment, act even if some minor details are missing.
4. If the transcript is garbled, use only the clear parts and ignore noise.

RECONFIRMATIONS:
If the transcript is only repeating, confirming, or clarifying an already-created plan, do not create a duplicate event.
No tool examples:
- "yeah, so we're meeting at 6, right?"
- "ok, noon tomorrow then"
- "same place as before"
- "see you at 3"
Only call a tool if new important information changes the existing plan.

CANCELLATIONS, REJECTIONS, AND AVAILABILITY CONFLICTS:
Cancel or do not create an event when ANY speaker clearly indicates the plan is no longer happening, they cannot attend, or the proposed time does not work. This includes direct cancellations, soft rejections, and availability conflicts.

If an event was already created recently and the transcript now contains one of these meanings, call cancel_last_event:
- "cancel that"
- "never mind"
- "actually forget it"
- "I'm actually busy, sorry"
- "I can't make it"
- "let's not do it anymore"
- "rain check?"
- "maybe another time"
- "I have to reschedule"
- "that won't work for me"
- "sorry, I'm not free then"
- "actually I have practice/class/work then"

If no event was created yet and the transcript is rejecting a proposed plan, call no tool.

PROPOSALS VS COMMITMENTS:
Do not create an event for vague or hypothetical discussion.
No tool:
- "we should get lunch sometime"
- "maybe we can meet next week"
- "I might go to the gym later"
- "let's figure it out"

Create an event:
- "let's get lunch tomorrow at noon"
- "dinner at 7 tonight?" followed by acceptance or clear agreement
- "yeah, that works"
- "see you tomorrow at 3"
- "call me at 6"

If one person proposes a plan and the other accepts or agrees, create the event. If one person proposes and the other declines, do not create the event.

EXAMPLES:
Transcript: "Let's get lunch tomorrow at noon. Yeah, sounds good."
Tool: create_calendar_event(title="Lunch", event_type="lunch", start_iso=<resolved noon tomorrow>)

Transcript: "Want to grab boba at 4? Sure."
Tool: create_calendar_event(title="Boba", event_type="boba", start_iso=<resolved 4pm>)

Transcript: "Let's meet tomorrow at 5 to go over the project."
Tool: create_calendar_event(title="Project Meeting", event_type="meeting", start_iso=<resolved 5pm tomorrow>)

Transcript: "Lunch tomorrow at noon? Actually I'm busy, sorry."
Tool: none

Transcript after recently creating lunch: "Actually I'm busy, sorry, rain check?"
Tool: cancel_last_event()

ONLY when there is genuinely no actionable plan, event, reminder, cancellation, or to-do, call no tool and reply "none".
"""


def process_transcript(conversation: str) -> list[str]:
    """Send conversation to Claude; execute any tool calls. Returns log lines."""
    system = build_system_prompt()

    response = client.messages.create(
        model="claude-haiku-4-5",  # fastest + cheapest; great for this task
        max_tokens=1024,
        system=system,
        tools=TOOLS,
        messages=[{"role": "user", "content": f"Conversation so far:\n{conversation}"}],
    )

    logs = []
    for block in response.content:
        if block.type == "tool_use":
            result = execute_tool(block.name, block.input)
            logs.append(result)
    return logs


def execute_tool(name: str, args: dict) -> str:
    if name == "create_calendar_event":
        # Backend guard against Claude overusing generic titles such as "Meeting".
        title = _specific_title_from_args(args)
        args["title"] = title

        key = _event_key(args["title"], args["start_iso"])
        now = time.monotonic()
        # Purge stale entries first.
        _recent_events[:] = [e for e in _recent_events if now - e["created_at"] < DEDUP_WINDOW_SECONDS]
        # Deduplicate: if we already created this event recently, skip it.
        for recent in _recent_events:
            if recent["key"] == key:
                return f"⏭️  Already scheduled '{args['title']}' — skipping reconfirmation"

        # Preserve structured metadata in notes without requiring calendar_tool changes.
        notes_parts = []
        if args.get("notes"):
            notes_parts.append(str(args["notes"]))
        if args.get("event_type"):
            notes_parts.append(f"Type: {_clean_event_type(args.get('event_type'))}")
        if args.get("participants"):
            participants = args["participants"]
            if isinstance(participants, list):
                participants_text = ", ".join(str(p) for p in participants if p)
            else:
                participants_text = str(participants)
            if participants_text:
                notes_parts.append(f"Participants: {participants_text}")
        notes = "\n".join(notes_parts) if notes_parts else None

        result = calendar_tool.create_event(
            title=args["title"],
            start_iso=args["start_iso"],
            duration_minutes=args.get("duration_minutes", 60),
            location=args.get("location"),
            notes=notes,
        )
        # Extract event id from the result URL to support cancellation.
        event_id = None
        if "eid=" in result:
            try:
                event_id = result.split("eid=")[1].split("&")[0]
            except IndexError:
                pass
        _recent_events.append({
            "key": key,
            "title": args["title"],
            "start_iso": args["start_iso"],
            "event_id": event_id,
            "created_at": now,
        })
        return result

    if name == "cancel_last_event":
        now = time.monotonic()
        _recent_events[:] = [e for e in _recent_events if now - e["created_at"] < DEDUP_WINDOW_SECONDS]
        if not _recent_events:
            return "⚠️  No recent event to cancel"
        last = _recent_events.pop()
        if not last.get("event_id"):
            return f"⚠️  Can't cancel '{last['title']}' — event ID not available"
        return calendar_tool.delete_event(last["event_id"])

    if name == "create_task":
        return calendar_tool.create_task(
            title=args["title"], due_iso=args.get("due_iso")
        )
    return f"[unknown tool: {name}]"
