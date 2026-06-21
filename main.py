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
MAX_BUFFER_CHARS = 600

_transcript: list[str] = []
_last_speech = 0.0
_dirty = False


def on_final(text: str):
    global _last_speech, _dirty
    print(f"\n🗣️  {text}")
    _transcript.append(text)
    _last_speech = time.monotonic()
    _dirty = True


async def flusher():
    global _dirty, _transcript
    while True:
        await asyncio.sleep(0.25)
        if not _dirty:
            continue
        if time.monotonic() - _last_speech < SILENCE_FLUSH_SECONDS:
            continue
        _dirty = False
        # Rolling context so a request spread across pauses is seen as a whole.
        conversation = " ".join(_transcript)[-MAX_BUFFER_CHARS:]
        if len(_transcript) > 10:
            _transcript = _transcript[-10:]
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
