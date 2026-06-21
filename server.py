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
import re
import time

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import agent
import calendar_tool
import geo
import router_client
from demo import CONVO
from face_gate import FaceGate
from transcribe import stream_microphone, stream_from_queue

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

# The running event loop, captured at startup so background threads (the agentic
# router's executor) can push result cards back onto the loop thread-safely.
_main_loop: asyncio.AbstractEventLoop | None = None

# Capture modes (distinct from MODE, which is the calendar mock/live badge):
#   conversation — passive, only captures when a face is in view (FaceGate)
#   solo         — only acts on commands prefixed with the wake phrase
CAPTURE_MODE = "solo"
WAKE_PHRASE = "mark this"
STOP_KEYWORD = "mydong"  # say this to stop listening and return to idle
face_gate = FaceGate()

# Solo-mode: a command ending on one of these (a transitive verb or a dangling
# preposition/article) is probably mid-sentence — wait a little longer for the
# rest before acting, so "mark this, find … <pause> … EV chargers near me"
# doesn't fire as just "find".
SOLO_INCOMPLETE_GRACE = 4.0  # seconds of extra patience for an unfinished command
_DANGLING_TAIL = {
    "find", "search", "play", "add", "order", "text", "call", "get", "buy",
    "remind", "email", "send", "navigate", "set", "make", "show", "look",
    "book", "schedule", "to", "for", "a", "an", "the", "me", "my", "up", "on",
    "with", "and", "of", "near",
}

# --- pipeline buffer (ephemeral: held only until it acts or the moment passes) ---
SILENCE_FLUSH_SECONDS = 1.5     # quiet gap before we send a flush to the agent
CHAT_FLUSH_SECONDS = 0.8        # snappier gap once we're mid-conversation with Mark
IDLE_CLEAR_SECONDS = 20         # clear the buffer ~20s after the last speech
RECORD_SILENCE_SECONDS = 8.0    # record mode: silence gap that signals end of conversation
MAX_AGE_SECONDS = 20            # hard guarantee: nothing held older than ~20s
# Short rolling window so recent clean speech dominates and old chatter doesn't
# linger and poison new requests.
MAX_BUFFER_CHARS = 600
_transcript: list[dict] = []   # each: {"t": text, "ts": monotonic}
_last_speech = 0.0
_dirty = False
_mic_task: asyncio.Task | None = None
_ray_ban_audio_active = False   # True while /ws/audio-in is connected; bypasses face gate
_record_buffer: list[str] = []  # record mode: compressed note per speech chunk

# Talk-back: iPhone sockets we can push spoken replies to, plus the live
# conversation state for the "mark" chat trigger.
iphone_clients: set[WebSocket] = set()
_chat_active = False              # True while the wearer is mid-conversation with Mark
_chat_history: list[dict] = []    # rolling [{role, content}] for the chat responder
# While Mark is speaking, his voice bleeds back through the open mic. Ignore any
# transcript that lands before this monotonic deadline so he doesn't hear himself.
_suppress_capture_until = 0.0


def _speak_seconds(text: str) -> float:
    """Rough spoken duration estimate (~150 wpm) used to mute self-capture."""
    return len(text.split()) / 2.5 + 1.0


_GREETINGS = {"hey", "yo", "ok", "okay", "hi", "hello", "um", "uh", "so"}


def _is_chat_trigger(text: str) -> bool:
    """True when the wearer calls 'Mark' (to chat) rather than 'mark this' (command).

    Fires when 'mark' is the first or last spoken word, or follows a greeting —
    a name-call — but not when it's buried mid-sentence or part of 'mark this'."""
    low = text.lower()
    if WAKE_PHRASE in low:  # "mark this" → that's the command trigger, not chat
        return False
    toks = re.findall(r"[a-z']+", low)
    if "mark" not in toks:
        return False
    if toks[0] == "mark" or toks[-1] == "mark":
        return True
    if len(toks) >= 2 and toks[0] in _GREETINGS and toks[1] == "mark":
        return True
    return False


async def _stop_listening():
    """Cancel the mic task and return the UI to idle."""
    global _mic_task, _transcript, _dirty, _chat_active
    _transcript.clear()
    _dirty = False
    _record_buffer.clear()
    _chat_active = False
    _chat_history.clear()
    face_gate.stop()
    await broadcast({"type": "forgotten"})
    await broadcast({"type": "record_cleared"})
    await broadcast({"type": "status", "text": "idle"})
    if _mic_task and not _mic_task.done():
        _mic_task.cancel()


INTENTION_PIPE = "/tmp/intention.pipe"

def _write_intention(command: str):
    """Write the intention sentence to a FIFO so an external terminal can pick it up."""
    try:
        if not os.path.exists(INTENTION_PIPE):
            os.mkfifo(INTENTION_PIPE)
        # Open non-blocking so we don't stall if nobody is reading
        fd = os.open(INTENTION_PIPE, os.O_WRONLY | os.O_NONBLOCK)
        with os.fdopen(fd, "w") as f:
            f.write(command + "\n")
    except (OSError, BrokenPipeError):
        pass  # no reader attached — silently drop


async def broadcast(msg: dict):
    for ws in list(clients):
        try:
            await ws.send_json(msg)
        except Exception:
            clients.discard(ws)


async def say(text: str):
    """Speak back to the wearer: shown as Mark's bubble on the HUD and read aloud
    on the iPhone (AVSpeechSynthesizer → glasses). Also opens a self-capture mute
    window so Mark's own voice doesn't loop back through the mic."""
    global _suppress_capture_until
    text = (text or "").strip()
    if not text:
        return
    _suppress_capture_until = time.monotonic() + _speak_seconds(text)
    msg = {"type": "say", "text": text}
    for ws in list(clients):
        try:
            await ws.send_json(msg)
        except Exception:
            clients.discard(ws)
    for ws in list(iphone_clients):
        try:
            await ws.send_json(msg)
        except Exception:
            iphone_clients.discard(ws)


def _emit_router_event(ev: dict):
    """Thread-safe sink for the agentic router. agent.py's background dispatch
    threads call this with the router's live reasoning ('thinking') and its final
    result; we hop back onto the event loop and broadcast to the HUD."""
    if _main_loop is None:
        return
    kind = ev.get("kind")
    if kind == "thinking":
        msg = {"type": "thinking", "text": ev.get("text", "")}
    elif kind == "result":
        msg = {"type": "action", "text": ev.get("text", "")}
    else:
        return
    asyncio.run_coroutine_threadsafe(broadcast(msg), _main_loop)


@app.on_event("startup")
async def _on_startup():
    global _main_loop
    _main_loop = asyncio.get_running_loop()
    agent.set_action_sink(_emit_router_event)  # stream router thinking + results
    # Warm the location cache off the event loop so the first intent isn't
    # stalled by the IP-geolocation lookup.
    loc = await asyncio.to_thread(geo.get_location)
    if loc and loc.get("label"):
        print("  📍 location:", loc["label"])
    if router_client.health():
        print("  ✅ agentic router reachable at", router_client.ROUTER_URL)
    else:
        print("  ⚠️  agentic router NOT reachable at", router_client.ROUTER_URL,
              "— start it with `npm run serve` (perform_action cards still show,",
              "but won't execute).")


async def _wake_now():
    """Hey-Siri-style instant wake: bare 'mark' greets right away, no silence wait.
    _chat_active is already set True by the caller to prevent a double-trigger."""
    global _transcript, _dirty
    _chat_history.clear()
    _transcript = []
    _dirty = False
    greeting = "Hey, I'm here — what's up?"
    _chat_history.append({"role": "assistant", "content": greeting})
    print(f"💬 WAKE → chat mode opened; greeting: {greeting!r}")
    await say(greeting)


def on_final(text: str):
    global _last_speech, _dirty, _chat_active
    if STOP_KEYWORD and STOP_KEYWORD.lower() in text.lower():
        print(f"🛑 stop keyword heard in: {text!r}")
        asyncio.create_task(_stop_listening())
        return
    if time.monotonic() < _suppress_capture_until:
        print(f"🔇 (ignored — Mark is speaking) {text!r}")
        return  # Mark is talking — this is his own voice bleeding into the mic
    if CAPTURE_MODE == "conversation" and not _ray_ban_audio_active and not face_gate.is_present():
        return  # no face in view — not capturing
    now = time.monotonic()

    # DEBUG: every recognized sentence, with the running paragraph it's part of.
    print(f"📝 [{CAPTURE_MODE}{'/chat' if _chat_active else ''}] sentence: {text!r}")

    # Hey-Siri reaction: a bare "mark" opens the conversation instantly instead
    # of waiting out the normal silence-flush window. Set the flag synchronously
    # so a quick second "mark" can't fire a second greeting.
    if CAPTURE_MODE == "solo" and not _chat_active and _is_chat_trigger(text):
        _chat_active = True
        asyncio.create_task(_wake_now())
        return

    _transcript.append({"t": text, "ts": now})
    _last_speech = now
    _dirty = True
    paragraph = " ".join(e["t"] for e in _transcript)
    print(f"📄 paragraph so far: {paragraph!r}")
    asyncio.create_task(broadcast({"type": "caption", "final": True, "text": text}))


def on_interim(text: str):
    if CAPTURE_MODE == "conversation" and not _ray_ban_audio_active and not face_gate.is_present():
        return
    asyncio.create_task(broadcast({"type": "caption", "final": False, "text": text}))


def on_level(level: float):
    asyncio.create_task(broadcast({"type": "level", "value": round(level, 3)}))


def on_entities(entities):
    agent.add_entities(entities)  # cache for pronoun resolution ("buy them")
    vals = [e.get("value") for e in entities if e.get("value")]
    if vals:
        asyncio.create_task(broadcast({"type": "entities", "values": vals}))


async def _process_and_broadcast(conversation: str, speak_result: bool = True) -> bool:
    print(f"→ sending to Claude: {conversation!r}")
    await broadcast({"type": "status", "text": "thinking"})
    acted = False
    try:
        results = await asyncio.to_thread(agent.process_transcript, conversation)
        print(f"← Claude result: {results}")
        if results:
            for line in results:
                if line.startswith("❓CLARIFY|"):
                    parts = line.split("|", 2)
                    q = parts[1] if len(parts) > 1 else "Which one did you mean?"
                    opts = [o for o in (parts[2].split("||") if len(parts) > 2 else []) if o]
                    await broadcast({"type": "clarify", "question": q, "options": opts})
                else:
                    acted = True
                    await broadcast({"type": "action", "text": line})
            # Speak a short, warm confirmation once the task is done.
            if acted and speak_result:
                spoken = await asyncio.to_thread(agent.spoken_confirmation, results)
                if spoken:
                    await say(spoken)
        else:
            await broadcast({"type": "action", "text": "💬 (no action — chit-chat)", "muted": True})
    except Exception as e:
        print(f"✗ error: {e!r}")
        await broadcast({"type": "action", "text": f"⚠️ {e}", "muted": True})
    await broadcast({"type": "status", "text": "listening"})
    return acted


async def flusher():
    global _dirty, _transcript, _chat_active
    while True:
        await asyncio.sleep(0.25)
        now = time.monotonic()

        # Backstop: drop any utterance older than the max age.
        if _transcript:
            kept = [e for e in _transcript if now - e["ts"] < MAX_AGE_SECONDS]
            if len(kept) != len(_transcript):
                _transcript = kept
                if not _transcript:  # buffer just emptied — tell the HUD to clear
                    await broadcast({"type": "forgotten"})

        # RECORD MODE — two-stage passive summariser
        if CAPTURE_MODE == "record":
            # Stage 1: compress the latest speech chunk after the usual silence gap
            if _dirty and now - _last_speech >= SILENCE_FLUSH_SECONDS:
                _dirty = False
                chunk = " ".join(e["t"] for e in _transcript)[-MAX_BUFFER_CHARS:]
                _transcript.clear()
                note = await asyncio.to_thread(agent.compress_sentence, chunk)
                print(f"📝 RECORD chunk: {chunk!r} → note: {note!r}")
                if note and note.lower() not in ("none", ""):
                    _record_buffer.append(note)
                    print(f"📄 RECORD paragraph ({len(_record_buffer)} notes): {_record_buffer}")
                    await broadcast({"type": "record_note", "text": note})
            # Stage 2: after a long gap of silence, synthesise all notes → command
            if _record_buffer and not _dirty and _last_speech > 0 and now - _last_speech >= RECORD_SILENCE_SECONDS:
                notes = list(_record_buffer)
                _record_buffer.clear()
                await broadcast({"type": "record_cleared"})
                command = await asyncio.to_thread(agent.synthesize_command, notes)
                print(f"🧩 RECORD synthesized command from {notes} → {command!r}")
                if command and command.lower() not in ("none", ""):
                    directive = (
                        "Direct command from the wearer — perform it now, "
                        "inferring the action verb and app if implied: " + command
                    )
                    await _process_and_broadcast(directive)
            continue  # record mode owns its own flow; never fall through

        # Constraint 2 — clear after a lull: nothing pending and the room has
        # gone quiet, so the moment passed. Forget what was said.
        if _transcript and not _dirty and now - _last_speech > IDLE_CLEAR_SECONDS:
            _transcript = []
            await broadcast({"type": "forgotten"})
            continue

        if not _dirty:
            continue
        # Snappier turn-taking once we're mid-conversation; calmer otherwise.
        flush_gap = CHAT_FLUSH_SECONDS if _chat_active else SILENCE_FLUSH_SECONDS
        if now - _last_speech < flush_gap:
            continue
        _dirty = False

        # Rolling context so a request split across pauses is seen as one whole.
        conversation = " ".join(e["t"] for e in _transcript)[-MAX_BUFFER_CHARS:]
        if len(_transcript) > 10:
            _transcript = _transcript[-10:]

        if CAPTURE_MODE == "solo":
            # (1) Mid-conversation with Mark — every utterance is a chat turn.
            if _chat_active:
                text = conversation.strip()
                _transcript = []
                if not text:
                    continue
                print(f"💬 YOU said: {text!r}")
                await broadcast({"type": "status", "text": "thinking"})
                turn = await asyncio.to_thread(agent.converse, text, _chat_history)
                print(f"💬 MARK reply: {turn['reply']!r} | end={turn['end']} | task={turn.get('task')!r}")
                _chat_history.append({"role": "user", "content": text})
                _chat_history.append({"role": "assistant", "content": turn["reply"]})
                await say(turn["reply"])
                if turn.get("task"):
                    # The wearer asked for something concrete mid-chat — do it.
                    # The spoken reply already acknowledged it, so don't double-speak.
                    _write_intention(turn["task"])
                    await _process_and_broadcast(
                        "Direct command from the wearer — perform it now, inferring "
                        "the action verb and app if implied: " + turn["task"],
                        speak_result=False,
                    )
                if turn["end"]:
                    _chat_active = False
                    _chat_history.clear()
                await broadcast({"type": "status", "text": "listening"})
                continue

            # (2) Bare "mark" (a name-call) opens a back-and-forth conversation.
            if _is_chat_trigger(conversation):
                _chat_active = True
                _chat_history.clear()
                _transcript = []
                greeting = "Hey, I'm here — what's up?"
                _chat_history.append({"role": "assistant", "content": greeting})
                await say(greeting)
                continue

            # (3) "mark this <command>" — explicit one-shot command (overrides
            # ambient: act on exactly what's said after the wake phrase).
            i = conversation.lower().rfind(WAKE_PHRASE)
            if i != -1:
                command = conversation[i + len(WAKE_PHRASE):].lstrip(" ,.:;—-").strip()
                if not command:
                    # heard "mark this" but the command hasn't been spoken yet —
                    # wait so the next utterance combines with the trigger.
                    continue
                # If the command looks unfinished (one word, or ends on a transitive
                # verb / preposition), wait a few extra seconds for the rest.
                words = command.split()
                tail = words[-1].lower().strip(",.?!;:") if words else ""
                unfinished = len(words) < 2 or tail in _DANGLING_TAIL
                if unfinished and (now - _last_speech) < SOLO_INCOMPLETE_GRACE:
                    _dirty = True  # re-check next tick; combine with further speech
                    continue
                _transcript = []  # consume the whole buffer
                directive = (
                    "Direct command from the wearer — perform it now, inferring the "
                    "action verb and app if implied: " + command
                )
                _write_intention(command)
                await _process_and_broadcast(directive)
                continue

            # (4) AMBIENT auto-add — no wake phrase. Listen to the natural
            # conversation and let the agent add an event the MOMENT a plan has
            # the minimum details (a date + time). The agent dedups, so the
            # growing paragraph won't re-add the same event; later lines that add
            # a location or a person update it instead. The buffer lingers (not
            # cleared here) so those follow-up details still have context.
            print(f"🔎 ambient check → {conversation!r}")
            await _process_and_broadcast(conversation)
            continue

        # Non-solo capture modes (e.g. Conversation) — ambient processing.
        acted = await _process_and_broadcast(conversation)
        if acted:
            _write_intention(conversation)
        # NOT cleared instantly on action — the buffer lingers ~20s (see
        # IDLE_CLEAR_SECONDS / MAX_AGE_SECONDS) so quick follow-ups like
        # "actually move it to 8" keep context. Dedup stops the lingering text
        # from re-firing the same action.


async def _face_status_loop():
    last = None
    while True:
        await asyncio.sleep(0.4)
        state = ("off" if not face_gate.camera_ok()
                 else "present" if face_gate.is_present() else "absent")
        if state != last:
            last = state
            await broadcast({"type": "face", "state": state})


async def mic_loop():
    if CAPTURE_MODE == "conversation":
        face_gate.start()  # on-device camera gate (Conversation mode only)
    asyncio.create_task(_face_status_loop())
    await broadcast({"type": "status", "text": "listening"})
    try:
        await asyncio.gather(
            stream_microphone(
                on_final, on_interim, on_level=on_level, on_entities=on_entities
            ),
            flusher(),
        )
    except Exception as e:
        await broadcast({"type": "status", "text": "mic error"})
        await broadcast({"type": "action", "text": f"⚠️ mic: {e}", "muted": True})


async def run_demo():
    """Replay the scripted conversation through the real Claude pipeline."""
    agent._recent_events.clear()
    agent._recent_actions.clear()
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
    return FileResponse("web/dist/index.html")


@app.get("/config")
async def config():
    loc = geo.get_location()
    return {
        "mode": MODE,
        "cal_embed": CAL_EMBED,
        "location": loc.get("label") if loc else None,
    }


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    global _mic_task, _dirty, CAPTURE_MODE
    await ws.accept()
    clients.add(ws)
    await ws.send_json({"type": "status", "text": "idle", "mode": MODE})
    await ws.send_json({"type": "capturemode", "mode": CAPTURE_MODE})
    try:
        while True:
            data = await ws.receive_json()
            cmd = data.get("cmd")
            if cmd == "demo":
                asyncio.create_task(run_demo())
            elif cmd == "mic":
                if _mic_task is None or _mic_task.done():
                    _mic_task = asyncio.create_task(mic_loop())
            elif cmd == "capturemode":
                m = data.get("mode")
                if m in ("conversation", "solo", "record"):
                    CAPTURE_MODE = m
                    _transcript.clear()
                    _dirty = False
                    _record_buffer.clear()
                    await broadcast({"type": "record_cleared"})
                    if m in ("solo", "record"):
                        face_gate.stop()  # no camera gate in solo / record mode
                    elif _mic_task and not _mic_task.done():
                        face_gate.start()  # back to Conversation while miced → camera on
                    await broadcast({"type": "capturemode", "mode": CAPTURE_MODE})
            elif cmd == "answer":
                # User picked a clarification option — resolve it through the
                # agent (the entity cache still holds the referenced item).
                ans = (data.get("text") or "").strip()
                if ans:
                    await broadcast({"type": "caption", "final": True, "text": ans})
                    asyncio.create_task(_process_and_broadcast(ans))
            elif cmd == "reset":
                agent._recent_events.clear()
                agent._recent_actions.clear()
                agent._entity_cache.clear()
                _transcript.clear()
                _dirty = False
                await broadcast({"type": "reset"})
                await broadcast({"type": "status", "text": "idle"})
    except WebSocketDisconnect:
        clients.discard(ws)


@app.websocket("/ws/audio-in")
async def audio_in_endpoint(ws: WebSocket):
    """Raw PCM16 audio from the Ray-Ban relay → Deepgram → flusher → agent.

    Protocol (from WeMightBeCooked/server.py):
      1. JSON  {"type": "audio_config", "sample_rate": N}
      2. binary chunks of PCM16 mono audio
      3. JSON  {"type": "audio_stop"}  or just disconnect when done
    """
    global _ray_ban_audio_active
    await ws.accept()
    _ray_ban_audio_active = True
    print("Ray-Ban audio relay connected")
    await broadcast({"type": "status", "text": "listening"})
    await broadcast({"type": "rayban", "connected": True})

    audio_queue: asyncio.Queue = asyncio.Queue()
    stream_task: asyncio.Task | None = None

    async def _start_stream(sample_rate: int):
        nonlocal stream_task, audio_queue
        if stream_task and not stream_task.done():
            await audio_queue.put(None)
            stream_task.cancel()
        audio_queue = asyncio.Queue()
        stream_task = asyncio.create_task(
            stream_from_queue(
                on_final, on_interim,
                audio_queue=audio_queue,
                sample_rate=sample_rate,
                on_level=on_level,
                on_entities=on_entities,
            )
        )
        # Start the flusher if the Mic button was never pressed
        global _mic_task
        if _mic_task is None or _mic_task.done():
            _mic_task = asyncio.create_task(flusher())

    try:
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                break
            if "text" in message:
                import json as _json
                data = _json.loads(message["text"])
                if data.get("type") == "audio_config":
                    await _start_stream(int(data.get("sample_rate", 16000)))
                elif data.get("type") == "audio_stop":
                    await audio_queue.put(None)
            elif "bytes" in message:
                await audio_queue.put(message["bytes"])
    except WebSocketDisconnect:
        pass
    finally:
        _ray_ban_audio_active = False
        await audio_queue.put(None)
        if stream_task:
            stream_task.cancel()
        print("Ray-Ban audio relay disconnected")
        await broadcast({"type": "rayban", "connected": False})
        await broadcast({"type": "status", "text": "idle"})


@app.websocket("/ws/iphone")
async def iphone_endpoint(ws: WebSocket):
    """iPhone / Ray-Ban audio+video directly on port 8000 — no relay needed.

    Identical protocol to /ws/audio-in plus optional video frames:
      1. JSON  {"type": "audio_config", "sample_rate": N}
      2. binary chunks of PCM16 mono audio
      3. JSON  {"type": "image", "image_base64": "<jpeg>"}   (optional, ignored by HUD)
      4. JSON  {"type": "audio_stop"}  or just disconnect
    """
    global _ray_ban_audio_active
    await ws.accept()
    _ray_ban_audio_active = True
    iphone_clients.add(ws)  # so Mark can speak back to the glasses
    print("iPhone connected on /ws/iphone")
    await broadcast({"type": "status", "text": "listening"})
    await broadcast({"type": "rayban", "connected": True})

    audio_queue: asyncio.Queue = asyncio.Queue()
    stream_task: asyncio.Task | None = None

    async def _start_stream(sample_rate: int):
        nonlocal stream_task, audio_queue
        if stream_task and not stream_task.done():
            await audio_queue.put(None)
            stream_task.cancel()
        audio_queue = asyncio.Queue()
        stream_task = asyncio.create_task(
            stream_from_queue(
                on_final, on_interim,
                audio_queue=audio_queue,
                sample_rate=sample_rate,
                on_level=on_level,
                on_entities=on_entities,
            )
        )
        global _mic_task
        if _mic_task is None or _mic_task.done():
            _mic_task = asyncio.create_task(flusher())

    try:
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                break
            if "text" in message:
                import json as _json
                data = _json.loads(message["text"])
                msg_type = data.get("type")
                if msg_type == "audio_config":
                    await _start_stream(int(data.get("sample_rate", 16000)))
                elif msg_type == "audio_stop":
                    await audio_queue.put(None)
                # video frames (type == "image") are silently dropped — the HUD
                # uses the laptop webcam for the face mesh overlay
            elif "bytes" in message:
                await audio_queue.put(message["bytes"])
    except WebSocketDisconnect:
        pass
    finally:
        _ray_ban_audio_active = False
        iphone_clients.discard(ws)
        await audio_queue.put(None)
        if stream_task:
            stream_task.cancel()
        print("iPhone disconnected from /ws/iphone")
        await broadcast({"type": "rayban", "connected": False})
        await broadcast({"type": "status", "text": "idle"})


app.mount("/assets", StaticFiles(directory="web/dist/assets"), name="assets")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    print(f"\n  👓 Glasses HUD  →  http://localhost:{port}   (calendar mode: {MODE.upper()})")
    if MODE == "mock" and os.path.exists("credentials.json"):
        print("  ℹ️  Running MOCK (Actions work, but not written to real calendar).")
        print("      Authorize once with `python test_calendar.py` to switch to LIVE.\n")
    else:
        print()
    uvicorn.run(app, host="0.0.0.0", port=port)
