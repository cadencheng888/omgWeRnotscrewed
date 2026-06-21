"""
Live microphone -> Deepgram streaming transcription.

This is the "audio portion." It opens whatever microphone is selected as the
system input (your laptop mic now; the paired Meta Ray-Ban mic on demo day —
no code change needed, you just pick the glasses as the input device) and
streams raw audio to Deepgram's real-time WebSocket endpoint.

It calls `on_final(text)` every time Deepgram finalizes a chunk of speech.
That callback is where the rest of the app (Claude -> Google Calendar) hooks in.

Run it standalone to just see transcripts:
    python transcribe.py
"""

import array
import asyncio
import json
import os

import sounddevice as sd
import websockets
from dotenv import load_dotenv

load_dotenv()

DEEPGRAM_URL = "wss://api.deepgram.com/v1/listen"

# Deepgram expects 16-bit PCM. 16 kHz mono is plenty for speech and keeps
# the upload tiny.
SAMPLE_RATE = 16000
CHANNELS = 1


def _build_url(sample_rate: int) -> str:
    params = {
        "model": "nova-3",          # Deepgram's latest general model
        "language": "en-US",
        "encoding": "linear16",     # raw 16-bit PCM, matches dtype="int16" below
        "sample_rate": str(sample_rate),
        "channels": str(CHANNELS),
        "smart_format": "true",     # nice formatting of times, numbers, etc.
        "punctuate": "true",
        "interim_results": "true",  # get live partials as someone speaks
        "endpointing": "300",       # ms of silence before finalizing an utterance
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{DEEPGRAM_URL}?{query}"


def _preferred_input_device():
    """Default to the built-in Mac mic (more reliable for demos than AirPods).

    Matches by name so it survives index changes / AirPods connecting. Returns
    None (= system default) if no built-in mic is found.
    """
    try:
        for i, d in enumerate(sd.query_devices()):
            name = d["name"].lower()
            if d["max_input_channels"] > 0 and ("macbook" in name or "built-in" in name):
                return i
    except Exception:
        pass
    return None


def _resolve_sample_rate(device) -> int:
    """Use 16 kHz if the device supports it; otherwise fall back to its default.

    Some mics (e.g. AirPods) don't expose 16 kHz mono, which would make
    RawInputStream raise at open. We probe first and, if needed, use the
    device's native rate (Deepgram is told the real rate via _build_url).
    """
    try:
        sd.check_input_settings(
            device=device, samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="int16"
        )
        return SAMPLE_RATE
    except Exception:
        info = sd.query_devices(device, "input")
        rate = int(info["default_samplerate"])
        print(f"[audio] {SAMPLE_RATE} Hz unsupported on this device; using {rate} Hz")
        return rate


async def stream_microphone(on_final, on_interim=None, device=None, on_level=None):
    """Stream the mic to Deepgram until cancelled (Ctrl+C).

    Reconnects automatically with exponential backoff if Deepgram drops the
    socket (network blip, idle timeout) so a long listening session survives.

    on_final(text):   called with each finalized utterance.
    on_interim(text): optional, called with live partial transcripts.
    device:           optional sounddevice input device index/name. None = default.
    """
    api_key = os.environ.get("DEEPGRAM_API_KEY")
    if not api_key:
        raise RuntimeError("Set DEEPGRAM_API_KEY in your .env file.")

    if device is None:
        device = _preferred_input_device()  # built-in Mac mic by default
    try:
        print(f"[audio] using input device: {sd.query_devices(device, 'input')['name']}")
    except Exception:
        pass

    sample_rate = _resolve_sample_rate(device)

    backoff = 1
    while True:
        try:
            await _stream_once(on_final, on_interim, device, api_key, sample_rate, on_level)
        except (asyncio.CancelledError, KeyboardInterrupt):
            raise
        except Exception as e:  # connection dropped — back off and reconnect
            print(f"[audio] connection lost ({e!r}); reconnecting in {backoff}s…")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)


async def _stream_once(on_final, on_interim, device, api_key, sample_rate, on_level=None):
    """One mic→Deepgram session; returns/raises when the socket closes."""
    loop = asyncio.get_running_loop()
    audio_queue: asyncio.Queue[bytes] = asyncio.Queue()

    # sounddevice calls this from a separate (non-async) thread for each audio
    # block, so we hand the bytes back to the event loop thread-safely.
    def audio_callback(indata, frames, time_info, status):
        if status:
            print(f"[audio] {status}")
        b = bytes(indata)
        loop.call_soon_threadsafe(audio_queue.put_nowait, b)
        if on_level is not None:  # emit a 0..1 mic level for the UI meter
            try:
                s = array.array("h")
                s.frombytes(b)
                peak = abs(max(s, key=abs)) if s else 0
                loop.call_soon_threadsafe(on_level, peak / 32767)
            except Exception:
                pass

    # websockets >=13 uses additional_headers; older versions use extra_headers.
    try:
        ws_ctx = websockets.connect(
            _build_url(sample_rate), additional_headers={"Authorization": f"Token {api_key}"}
        )
    except TypeError:
        ws_ctx = websockets.connect(
            _build_url(sample_rate), extra_headers={"Authorization": f"Token {api_key}"}
        )

    async with ws_ctx as ws:
        print("🎙️  Listening… (Ctrl+C to stop)")

        async def sender():
            stream = sd.RawInputStream(
                samplerate=sample_rate,
                channels=CHANNELS,
                dtype="int16",
                blocksize=4000,          # ~250 ms blocks
                device=device,
                callback=audio_callback,
            )
            with stream:
                while True:
                    chunk = await audio_queue.get()
                    await ws.send(chunk)

        async def receiver():
            async for message in ws:
                data = json.loads(message)
                if data.get("type") != "Results":
                    continue
                alt = data["channel"]["alternatives"][0]
                text = alt.get("transcript", "").strip()
                if not text:
                    continue
                if data.get("is_final"):
                    on_final(text)
                elif on_interim:
                    on_interim(text)

        # Keepalive so Deepgram doesn't close the socket during silence.
        async def keepalive():
            while True:
                await asyncio.sleep(8)
                await ws.send(json.dumps({"type": "KeepAlive"}))

        await asyncio.gather(sender(), receiver(), keepalive())


def list_devices():
    """Print available audio input devices and their indices."""
    print(sd.query_devices())


if __name__ == "__main__":
    import sys

    if "--devices" in sys.argv:
        list_devices()
        raise SystemExit(0)

    def show_final(text):
        print(f"\n✅ {text}")

    def show_interim(text):
        print(f"   … {text}", end="\r")

    try:
        asyncio.run(stream_microphone(show_final, show_interim))
    except KeyboardInterrupt:
        print("\n👋 stopped")
