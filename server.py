"""
Web "glasses HUD" for the audio agent.

    python server.py        # then open http://localhost:8000

Wraps the existing pipeline (transcribe.py + agent.py) — no changes to that
logic. Streams live captions and the actions Claude takes to the browser over a
WebSocket, and embeds your Google Calendar so events appear on screen.

Calendar mode is auto-detected:
  - credentials.json present  -> LIVE  (writes to your real calendar)
  - credentials.json missing  -> MOCK  (fake calendar so it still demos)
"""

import asyncio
import os
import time

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import agent
import calendar_tool
from demo import CONVO
from transcribe import stream_microphone

# --- Calendar mode: real if credentials exist, otherwise a mock so the HUD
#     demos immediately (before Google is connected). ---
# LIVE only when BOTH the client file AND a completed authorization exist —
# otherwise scheduling would block on the OAuth browser flow. Until you've
# authorized (token.json), we run MOCK so the HUD/Actions still work.
MODE = "live" if (os.path.exists("credentials.json") and os.path.exists("token.json")) else "mock"
if MODE == "mock":
    _n = [0]

    def _fake_create(title, start_iso, duration_minutes=60, location=None, notes=None):
        _n[0] += 1
        return f"📅 created '{title}' at {start_iso} [id:mock{_n[0]}]"

    calendar_tool.create_event = _fake_create
    calendar_tool.update_event = (
        lambda eid, start_iso=None, duration_minutes=None, **k: f"🔁 moved → {start_iso}"
    )
    calendar_tool.delete_event = lambda eid: "🗑️ cancelled"

# Your calendar, embedded. Override with the GCAL_EMBED env var if needed.
CAL_EMBED = os.environ.get(
    "GCAL_EMBED",
    "https://calendar.google.com/calendar/embed"
    "?src=cadencheng888%40gmail.com&mode=DAY",
)

app = FastAPI()
clients: set[WebSocket] = set()

# --- pipeline buffer (same logic as main.py) ---
SILENCE_FLUSH_SECONDS = 1.5
# Keep the rolling window short so recent clean speech dominates and old
# chatter / rejections don't linger and poison new requests.
MAX_BUFFER_CHARS = 600
_transcript: list[str] = []
_last_speech = 0.0
_dirty = False
_mic_task: asyncio.Task | None = None


async def broadcast(msg: dict):
    for ws in list(clients):
        try:
            await ws.send_json(msg)
        except Exception:
            clients.discard(ws)


def on_final(text: str):
    global _last_speech, _dirty
    _transcript.append(text)
    _last_speech = time.monotonic()
    _dirty = True
    asyncio.create_task(broadcast({"type": "caption", "final": True, "text": text}))


def on_interim(text: str):
    asyncio.create_task(broadcast({"type": "caption", "final": False, "text": text}))


def on_level(level: float):
    asyncio.create_task(broadcast({"type": "level", "value": round(level, 3)}))


async def _process_and_broadcast(conversation: str):
    print(f"→ sending to Claude: {conversation!r}")
    await broadcast({"type": "status", "text": "thinking"})
    try:
        results = await asyncio.to_thread(agent.process_transcript, conversation)
        print(f"← Claude result: {results}")
        if results:
            for line in results:
                await broadcast({"type": "action", "text": line})
        else:
            await broadcast({"type": "action", "text": "💬 (no action — chit-chat)", "muted": True})
    except Exception as e:
        print(f"✗ error: {e!r}")
        await broadcast({"type": "action", "text": f"⚠️ {e}", "muted": True})
    await broadcast({"type": "status", "text": "listening"})


async def flusher():
    global _dirty, _transcript
    while True:
        await asyncio.sleep(0.25)
        if not _dirty:
            continue
        if time.monotonic() - _last_speech < SILENCE_FLUSH_SECONDS:
            continue
        _dirty = False
        # Rolling context: keep recent speech so a request split across several
        # pauses ("schedule an event" … "for 6pm" … "at a cafe") is seen as one
        # whole request, not one fragment at a time. Dedup prevents repeats.
        conversation = " ".join(_transcript)[-MAX_BUFFER_CHARS:]
        if len(_transcript) > 10:
            _transcript = _transcript[-10:]
        await _process_and_broadcast(conversation)


async def mic_loop():
    await broadcast({"type": "status", "text": "listening"})
    try:
        await asyncio.gather(
            stream_microphone(on_final, on_interim, on_level=on_level), flusher()
        )
    except Exception as e:
        await broadcast({"type": "status", "text": "mic error"})
        await broadcast({"type": "action", "text": f"⚠️ mic: {e}", "muted": True})


async def run_demo():
    """Replay the scripted conversation through the real Claude pipeline."""
    agent._recent_events.clear()
    await broadcast({"type": "status", "text": "demo running"})
    for line in CONVO:
        # Stream word-by-word so captions look live.
        partial = ""
        for w in line.split():
            partial += (" " if partial else "") + w
            await broadcast({"type": "caption", "final": False, "text": partial})
            await asyncio.sleep(0.04)
        await broadcast({"type": "caption", "final": True, "text": line})
        await _process_and_broadcast(line)
        await asyncio.sleep(1.1)
    await broadcast({"type": "status", "text": "demo complete"})


@app.get("/")
async def index():
    return FileResponse("static/index.html")


@app.get("/config")
async def config():
    return {"mode": MODE, "cal_embed": CAL_EMBED}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    global _mic_task, _dirty
    await ws.accept()
    clients.add(ws)
    await ws.send_json({"type": "status", "text": "idle", "mode": MODE})
    try:
        while True:
            data = await ws.receive_json()
            cmd = data.get("cmd")
            if cmd == "demo":
                asyncio.create_task(run_demo())
            elif cmd == "mic":
                if _mic_task is None or _mic_task.done():
                    _mic_task = asyncio.create_task(mic_loop())
            elif cmd == "reset":
                agent._recent_events.clear()
                _transcript.clear()
                _dirty = False
                await broadcast({"type": "reset"})
                await broadcast({"type": "status", "text": "idle"})
    except WebSocketDisconnect:
        clients.discard(ws)


app.mount("/static", StaticFiles(directory="static"), name="static")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    print(f"\n  👓 Glasses HUD  →  http://localhost:{port}   (calendar mode: {MODE.upper()})")
    if MODE == "mock" and os.path.exists("credentials.json"):
        print("  ℹ️  Running MOCK (Actions work, but not written to real calendar).")
        print("      Authorize once with `python test_calendar.py` to switch to LIVE.\n")
    else:
        print()
    uvicorn.run(app, host="0.0.0.0", port=port)
