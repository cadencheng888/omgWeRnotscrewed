# Glasses Agent — audio pipeline

Passively listens to conversation → detects plans/to-dos → creates Google
Calendar events & Tasks. Built to run against a laptop mic now and the paired
Meta Ray-Ban mic later (the glasses expose their mic as a normal Bluetooth audio
input — no Meta SDK needed for audio).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then fill in DEEPGRAM_API_KEY + ANTHROPIC_API_KEY
```

### Google Calendar / Tasks
1. https://console.cloud.google.com → new project.
2. Enable **Google Calendar API** and **Google Tasks API**.
3. APIs & Services → Credentials → Create OAuth client ID → **Desktop app**.
4. Download as `credentials.json` into this folder.
5. First run opens a browser to authorize; a `token.json` is cached after.

## Run

```bash
python transcribe.py            # audio only — just print transcripts
python transcribe.py --devices  # list mic devices (find the glasses' index)
python main.py                  # full pipeline: mic -> Claude -> Calendar/Tasks
```

Try saying: *"Let's grab dinner at 6pm tonight."* — a few seconds after you
stop talking, the event appears in your calendar.

## Files
| file | role |
|------|------|
| `transcribe.py` | mic capture + Deepgram live streaming (the audio core) |
| `agent.py` | Claude reads transcript, decides which tool to call |
| `calendar_tool.py` | Google Calendar + Tasks API calls |
| `main.py` | wires mic → buffer → Claude → tools |

## Using the glasses
Pair the Ray-Ban Meta glasses to your machine over Bluetooth, then
`python transcribe.py --devices` to find their input index and pass
`device=<index>` to `stream_microphone(...)` in `main.py`.

## Extending (object detection, more apps)
- New external app (Spotify, Notion, reminders…): add a tool schema in
  `agent.py` `TOOLS` + a handler in `execute_tool`. Claude picks when to use it.
- Camera/object detection: requires the gated **Meta Wearables Device Access
  Toolkit** (camera frames → your phone app). Build that as a separate module
  feeding detections to the same agent.
