"""
Live pipeline: mic → Deepgram → Claude → Google Calendar.

    python main.py

Speak a plan ("lunch tomorrow at noon"), pause ~1.5 s, and it's on your calendar.
Ctrl+C to stop.
"""

import asyncio
import time

from agent import process_transcript
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
        print(f"🤖 processing: {conversation!r}")
        try:
            results = await asyncio.to_thread(process_transcript, conversation)
            for line in results:
                print(f"   ✅ {line}")
            if not results:
                print("   (nothing actionable)")
        except Exception as e:
            print(f"   ⚠️  {e}")


async def run():
    await asyncio.gather(stream_microphone(on_final), flusher())


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\n👋 stopped")
