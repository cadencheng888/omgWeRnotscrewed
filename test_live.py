"""
Live test: YOUR speech -> Deepgram -> Claude decision (printed, NOT executed).

Same pipeline as main.py, but instead of creating real Google events/tasks it
just prints what Claude decided. Lets you test the full mic + brain flow with
your own voice before setting up Google credentials.

    python test_live.py

Speak a plan ("let's grab lunch at noon tomorrow"), pause ~4 seconds, and watch
Claude's decision appear.
"""

import asyncio
import time

from agent import TOOLS, build_system_prompt, client
from transcribe import stream_microphone

SILENCE_FLUSH_SECONDS = 1.5
MAX_BUFFER_CHARS = 2000

_buffer: list[str] = []
_last_speech = 0.0


def on_final(text: str):
    global _last_speech
    print(f"\n🗣️  {text}")
    _buffer.append(text)
    _last_speech = time.monotonic()


def decide(conversation: str) -> str:
    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1024,
        system=build_system_prompt(),
        tools=TOOLS,
        messages=[{"role": "user", "content": f"Conversation so far:\n{conversation}"}],
    )
    tool_calls = [b for b in response.content if b.type == "tool_use"]
    if not tool_calls:
        return "   (nothing actionable)"
    lines = []
    for call in tool_calls:
        lines.append(f"   → WOULD CALL: {call.name}")
        for k, v in call.input.items():
            lines.append(f"        {k}: {v}")
    return "\n".join(lines)


async def flusher():
    global _buffer
    while True:
        await asyncio.sleep(0.25)
        if not _buffer:
            continue
        if time.monotonic() - _last_speech < SILENCE_FLUSH_SECONDS:
            continue
        conversation = " ".join(_buffer)[-MAX_BUFFER_CHARS:]
        _buffer = []
        print(f"🤖 thinking about: {conversation!r}")
        try:
            print(await asyncio.to_thread(decide, conversation))
        except Exception as e:
            print(f"⚠️  agent error: {e}")


async def run():
    await asyncio.gather(stream_microphone(on_final), flusher())


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\n👋 stopped")
