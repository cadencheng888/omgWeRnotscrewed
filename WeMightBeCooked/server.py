from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import uvicorn
import json

app = FastAPI()

viewers: set[WebSocket] = set()


@app.get("/")
def index():
    return HTMLResponse("""
<!DOCTYPE html>
<html>
<head>
  <title>iPhone / Ray-Ban Stream Viewer</title>
  <style>
    body {
      font-family: Arial, sans-serif;
      margin: 24px;
      background: #111;
      color: #eee;
    }
    h1 { margin-bottom: 8px; }
    #status { color: #9ee493; margin-bottom: 16px; }
    #camera {
      width: 640px;
      max-width: 100%;
      border: 2px solid #444;
      border-radius: 12px;
      background: #222;
    }
    #transcript {
      margin-top: 20px;
      padding: 16px;
      min-height: 120px;
      border: 1px solid #444;
      border-radius: 12px;
      background: #1b1b1b;
      font-size: 18px;
      line-height: 1.4;
      white-space: pre-wrap;
    }
    #log {
      margin-top: 20px;
      padding: 12px;
      max-height: 300px;
      overflow-y: auto;
      border: 1px solid #444;
      border-radius: 12px;
      background: #1b1b1b;
      font-family: monospace;
      font-size: 13px;
      line-height: 1.5;
    }
    #log div { padding: 2px 0; border-bottom: 1px solid #2a2a2a; }
    #log .time { color: #888; margin-right: 8px; }
  </style>
</head>
<body>
  <h1>Live iPhone / Ray-Ban Stream</h1>
  <div id="status">Waiting for iPhone...</div>

  <img id="camera" />

  <h2>Transcript</h2>
  <div id="transcript"></div>

  <h2>Log (newest at bottom, auto-scrolls)</h2>
  <div id="log"></div>

  <script>
    const statusEl = document.getElementById("status");
    const cameraEl = document.getElementById("camera");
    const transcriptEl = document.getElementById("transcript");
    const logEl = document.getElementById("log");

    function addLogLine(text) {
      const line = document.createElement("div");
      const time = new Date().toLocaleTimeString();
      line.innerHTML = '<span class="time">[' + time + ']</span>' + text;
      logEl.appendChild(line);
      logEl.scrollTop = logEl.scrollHeight;
    }

    const ws = new WebSocket(`ws://${location.host}/ws/view`);

    ws.onopen = () => {
      statusEl.textContent = "Dashboard connected. Waiting for iPhone stream...";
      addLogLine("Dashboard connected.");
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);

      if (data.type === "transcript") {
        transcriptEl.textContent = data.text || "";
        addLogLine("[transcript] " + (data.text || ""));
      }

      if (data.type === "image") {
        cameraEl.src = "data:image/jpeg;base64," + data.image_base64;
        addLogLine("[image] frame received");
      }

      if (data.type === "status") {
        statusEl.textContent = data.message;
        addLogLine(data.message);
      }
    };

    ws.onclose = () => {
      statusEl.textContent = "Dashboard disconnected.";
      addLogLine("Dashboard disconnected.");
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
        viewers.remove(websocket)


@app.websocket("/ws/iphone")
async def iphone_socket(websocket: WebSocket):
    await websocket.accept()
    print("iPhone connected")

    await broadcast({
        "type": "status",
        "message": "iPhone connected. Streaming..."
    })

    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)
            await broadcast(data)

    except WebSocketDisconnect:
        print("iPhone disconnected")
        await broadcast({
            "type": "status",
            "message": "iPhone disconnected."
        })


async def broadcast(data: dict):
    dead = []

    for viewer in viewers:
        try:
            await viewer.send_text(json.dumps(data))
        except Exception:
            dead.append(viewer)

    for viewer in dead:
        viewers.discard(viewer)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5050)