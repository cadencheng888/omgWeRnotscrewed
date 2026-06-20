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
import zoneinfo

from anthropic import Anthropic
from dotenv import load_dotenv

import calendar_tool

load_dotenv()

TZ_NAME = os.environ.get("LOCAL_TIMEZONE", "America/Los_Angeles")
client = Anthropic()  # reads ANTHROPIC_API_KEY from env

# Tool schemas Claude can choose to call. Keep descriptions concrete — Claude
# uses them to decide when each applies.
TOOLS = [
    {
        "name": "create_calendar_event",
        "description": (
            "Create a Google Calendar event. Use this when people in the "
            "conversation agree on plans at a specific time (e.g. 'let's meet "
            "at 6pm', 'dinner tomorrow at 7'). Only call when a time is clearly "
            "implied or stated."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short event title."},
                "start_iso": {
                    "type": "string",
                    "description": "Start time in ISO 8601 with offset, e.g. 2026-06-20T18:00:00-07:00.",
                },
                "duration_minutes": {
                    "type": "integer",
                    "description": "Event length in minutes. Default 60 if unclear.",
                },
                "location": {"type": "string", "description": "Location if mentioned."},
                "notes": {"type": "string", "description": "Any extra context."},
            },
            "required": ["title", "start_iso"],
        },
    },
    {
        "name": "create_task",
        "description": (
            "Create a Google Task / to-do. Use for action items without a fixed "
            "meeting time (e.g. 'remind me to buy milk', 'I need to email Sam')."
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
    return (
        "You are an assistant embedded in smart glasses that passively listens "
        "to the wearer's conversations. Detect actionable plans and to-dos and "
        "call the appropriate tool. Resolve relative times ('6pm', 'tomorrow') "
        f"against the current time: {_now_context()} (timezone {TZ_NAME}).\n"
        "IMPORTANT: You cannot ask the wearer follow-up questions — they are not "
        "in a chat and cannot reply. So whenever a plan has a clear time, ACT: "
        "create the event using the best title you can infer (e.g. 'Dinner') even "
        "if minor details like the other person's name or the location are missing. "
        "Never withhold an action just to ask for clarification. Speech is "
        "transcribed and may be garbled — extract intent from the clear parts and "
        "ignore the noise.\n"
        "Only when there is genuinely no plan or to-do at all, do not call any "
        "tool — just reply 'none'."
    )


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
        return calendar_tool.create_event(
            title=args["title"],
            start_iso=args["start_iso"],
            duration_minutes=args.get("duration_minutes", 60),
            location=args.get("location"),
            notes=args.get("notes"),
        )
    if name == "create_task":
        return calendar_tool.create_task(
            title=args["title"], due_iso=args.get("due_iso")
        )
    return f"[unknown tool: {name}]"
