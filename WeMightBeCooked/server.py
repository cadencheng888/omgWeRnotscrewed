"""
Ray-Ban / iPhone relay server.

Bridges the iOS app (RayBanCaptureManager) to the main glasses-HUD server
(server.py at port 8000). Two jobs:

  1. Video / status frames from the iPhone are broadcast to any browser
     viewers connected to /ws/view.
  2. Raw PCM16 audio from the Ray-Ban mic is forwarded — as binary frames —
     to the main server's /ws/audio-in endpoint, where the existing
     transcribe.py → Deepgram → agent.py pipeline takes over.

Run alongside the main server:
    python server.py                        # main HUD (port 8000)
    python WeMightBeCooked/server.py        # relay (port 5050)
"""

import json
import os

import uvicorn
import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

# Where the main glasses-HUD server is listening. Override via env if needed.
MAIN_SERVER_WS = os.environ.get("MAIN_SERVER_WS", "ws://localhost:8000")

app = FastAPI()
viewers: set[WebSocket] = set()


async def broadcast(data: dict):
    dead = []
    for viewer in viewers:
        try:
            await viewer.send_text(json.dumps(data))
        except Exception:
            dead.append(viewer)
    for v in dead:
        viewers.discard(v)


@app.get("/")
def index():
    return HTMLResponse("""
<!DOCTYPE html>
<html>
<head>
  <title>iPhone / Ray-Ban Stream Viewer</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 24px; background: #111; color: #eee; }
    h1 { margin-bottom: 8px; }
    #status { color: #9ee493; margin-bottom: 16px; }
    #camera { width: 640px; max-width: 100%; border: 2px solid #444; border-radius: 12px; background: #222; }
    #log {
      margin-top: 20px; padding: 12px; max-height: 300px; overflow-y: auto;
      border: 1px solid #444; border-radius: 12px; background: #1b1b1b;
      font-family: monospace; font-size: 13px; line-height: 1.5;
    }
    #log div { padding: 2px 0; border-bottom: 1px solid #2a2a2a; }
    #log .time { color: #888; margin-right: 8px; }
  </style>
</head>
<body>
  <h1>Ray-Ban Relay</h1>
  <div id="status">Waiting for iPhone...</div>
  <img id="camera" />
  <h2>Log</h2>
  <div id="log"></div>
  <script>
    const statusEl = document.getElementById("status");
    const cameraEl = document.getElementById("camera");
    const logEl    = document.getElementById("log");
    function addLog(text) {
      const d = document.createElement("div");
      d.innerHTML = '<span class="time">[' + new Date().toLocaleTimeString() + ']</span>' + text;
      logEl.appendChild(d);
      logEl.scrollTop = logEl.scrollHeight;
    }
    const ws = new WebSocket(`ws://${location.host}/ws/view`);
    ws.onopen  = () => { addLog("Relay viewer connected."); };
    ws.onclose = () => { statusEl.textContent = "Disconnected."; };
    ws.onmessage = (e) => {
      const d = JSON.parse(e.data);
      if (d.type === "image")  { cameraEl.src = "data:image/jpeg;base64," + d.image_base64; }
      if (d.type === "status") { statusEl.textContent = d.message; addLog(d.message); }
    };
  </script>
</body>
</html>
""")


@app.websocket("/ws/view")
async def viewer_socket(websocket: WebSocket):
    await websocket.accept()
    viewers.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        viewers.discard(websocket)


@app.websocket("/ws/iphone")
async def iphone_socket(websocket: WebSocket):
    await websocket.accept()
    print("iPhone connected")
    await broadcast({"type": "status", "message": "iPhone connected"})

    audio_relay: websockets.WebSocketClientProtocol | None = None

    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break

            if "text" in message:
                data = json.loads(message["text"])
                msg_type = data.get("type")

                if msg_type == "audio_config":
                    # Open (or reopen) the audio-in connection to the main server
                    if audio_relay is not None:
                        try:
                            await audio_relay.close()
                        except Exception:
                            pass
                    try:
                        audio_relay = await websockets.connect(
                            f"{MAIN_SERVER_WS}/ws/audio-in"
                        )
                        await audio_relay.send(message["text"])   # forward config
                        sr = data.get("sample_rate", "?")
                        await broadcast({"type": "status", "message": f"Audio relay open → main server ({sr} Hz)"})
                    except Exception as e:
                        audio_relay = None
                        print(f"[relay] couldn't reach main server: {e}")
                        await broadcast({"type": "status", "message": f"⚠️ main server unreachable: {e}"})

                elif msg_type == "audio_stop":
                    if audio_relay is not None:
                        try:
                            await audio_relay.send(message["text"])   # forward stop
                            await audio_relay.close()
                        except Exception:
                            pass
                        audio_relay = None
                    await broadcast({"type": "status", "message": "Audio relay closed"})

                else:
                    # Video frames, status messages — show in the relay viewer
                    await broadcast(data)

            elif "bytes" in message:
                # Raw PCM16 audio — forward directly to main server
                if audio_relay is not None:
                    try:
                        await audio_relay.send(message["bytes"])
                    except Exception as e:
                        print(f"[relay] audio send error: {e}")
                        audio_relay = None

    except WebSocketDisconnect:
        pass
    finally:
        if audio_relay is not None:
            try:
                await audio_relay.close()
            except Exception:
                pass
        print("iPhone disconnected")
        await broadcast({"type": "status", "message": "iPhone disconnected."})


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5050)
