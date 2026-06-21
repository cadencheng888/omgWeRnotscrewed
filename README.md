<p align="center">
  <img src="/remark_logo.jpeg" alt="remark. Logo" width="40%" height=auto>
  <br>
  Michelle Dong, Caden Cheng, Julia Jin, David Wan
</p>

## About Our Project & Significance
remark — stylized as "remark." — is a multi-agent operating system that marks down information based on remarks made in conversation. remark detects plans to grab dinner between two friends and automatically adds the event to your calendar. It keeps track of grocery lists, takes notes, sends texts, searches the web, and so much more — all without you ever touching a screen. remark selects and utilizes the optimal AI agent to carry out your everyday needs, making your life more convenient by helping you anywhere and everywhere. It works in the background, almost unnoticed, but there is nothing unremarkable about the benefits it brings. remark facilitates convenience without the risk of forgetting.

But remark's significance goes beyond convenience. Today, the AI agent ecosystem is vast and rapidly growing — there are specialized agents for shopping, scheduling, communication, research, navigation, and nearly every domain of everyday life. The problem is that accessing them requires knowing they exist, finding the right one, and navigating interfaces that were built for technically fluent users. The average person never touches an AI agent. That gap is what remark closes.

By living in a pair of glasses and listening to natural speech, remark becomes the universal entry point to the entire agent ecosystem — no dashboards, no prompts, no learning curve. A grandmother making plans over the phone benefits from the same AI infrastructure as a software engineer. A child saying "I want to get pizza tonight" gets the same outcome as someone who knows how to write a system prompt. The interface is just talking, something every person already knows how to do.

## Future Expansions & Applications
remark already runs hands-free on Meta Ray-Ban glasses (and works from a laptop mic with no app needed), listening for intent in ordinary conversation and turning it into real actions. Today, that means automatically creating, rescheduling, and canceling calendar events when you discuss, commit to, or back out of plans — plus routing shopping, messages, reminders, music, directions, and web lookups to an autonomous agent that actually carries them out. You don't have to do anything; remark marks it down for you. Here's where we're taking it next:
  - Smarter planning. Beyond detecting that you've made plans, remark will factor in travel time and overlapping events, and proactively notify you when you're at risk of being late or double-booked.
  - Live translation. remark is English-only today. We plan to have it bridge the language gap in real time: when it hears someone speaking a language you don't understand, it will transcribe and translate what they say — capturing intent, not just the literal words — and read it back to you, muting the other speaker while it translates so you only hear the translated speech.
  - Everyday assistance. remark can already take notes and run shopping and errand tasks through its web agent. We want to grow this into richer, longer-lived helpers — a running grocery or shopping list, and, once on-glasses vision is wired in, live situational coaching such as real-time baking advice ("mix more
  — it doesn't look light and fluffy yet").
- Somehow find a way to reduce latency when communicating between agents.
- Add video and implement our object-detection only pipeline.

## What Makes Us Unique
In this era of constant new hardware and innovation, privacy remains a major source of anxiety — and it's where remark is deliberately different. Plenty of existing technology does pieces of what remark's features do, but we combine them into one easy-to-use, multi-agent system: a tiered router that hands each request to the agent best suited to handle it — a specialized Fetch.ai agent, the calendar, or an autonomous web agent — which keeps the platform extendable and adaptable to unusual, even one-off situations it hasn't seen before.
Just as importantly, remark is built to minimize what it keeps. By default, nothing is persisted: the live transcript stays in memory and auto-clears seconds after the moment passes, and the only lasting record is the calendar event you actually wanted. We don't record or stream video — visual context is handled entirely on-device, where a face-presence check (running locally, with no frames ever leaving your device) gates passive listening. And if a feature ever needs to remember something longer — say, holding onto a grocery list for as long as you want it tracked — we ask first, so anything persistent is permission-based. remark is designed from the ground up to shrink the privacy surface, not expand it.

## Our Process
We started our project from the frustration that AI agents are everywhere and incredibly capable, but using one means knowing it exists, finding it, and learning to navigate a dashboard that may not be intuitive for those unfamiliar with them. Our project proposes a solution by asking: what's the most natural, always-on way to talk? Smart glasses. The process of voice in, real-world action out seeks to make AI agents accessible to everyone.

Step 1 — Hearing (audio → text)

We built the ears first. transcribe.py takes the Meta Ray-Ban glasses microphone and streams raw PCM16 audio to Deepgram's nova-3 model over a WebSocket, getting back live interim and final transcripts. We turned on Deepgram's entity detection early because we knew we'd later need to resolve pronouns like "buy them." We made it reconnect automatically with exponential backoff so a long listening session survives network blips.

Step 2 — Understanding (text → intent)

Next, the brain: agent.py. We gave Claude Haiku 4.5 a tool-calling schema and a carefully tuned prompt so it could read messy, real conversational speech and decide what's actually actionable — distinguishing a real plan from chit-chat, an active command from passive admiration ("play this" vs. "I love this song"). Our first concrete action was calendar events, executed through the Google Calendar API with a mock mode so the demo works even before you connect Google.

Step 3 — Seeing it (the HUD) + privacy

We built a React + Tailwind "glasses HUD" (server.py + web/) that streams live captions and action cards over WebSocket, with the calendar embedded so events appear instantly. Then we added the features that make ambient listening acceptable: an on-device face-presence gate using the laptop webcam (only listens when someone's actually talking to you — camera frames never leave the machine) and an ephemeral transcript buffer that auto-wipes itself 20 seconds after the moment passes.

Step 4 — Turning intent into action

The hardest part: making "add this to my cart" or "text Sarah I'm running late" actually happen, not just appear as a card on screen.

When Claude identifies a non-calendar action, it hands a natural-language intent string to our TypeScript agentic router (src/router.ts) running on a background thread — the optimistic card appears on the HUD immediately while the real work happens in parallel.

The router tries three tiers in order. First, it queries the Fetch.ai Agentverse marketplace to find a specialized agent for the task — searching for candidates by capability, then using Claude to judge the best match. Second, if the intent is calendar-shaped, it hits the Google Calendar API directly. Third, and most powerfully, it falls through to Browserbase + Stagehand: a cloud-hosted browser driven by Claude Sonnet 4.6 that can navigate and interact with essentially any website on the internet. The wearer's current location (resolved via IP geolocation) is baked into every intent string so "near me" and directions work correctly.

The router streams its reasoning back to the HUD as live "thinking" lines — so you can watch the agent decide, step by step, before the final result card lands.

## Privacy + Ethical Use of AI
The primary privacy concern related to our project is that the Meta Ray Ban microphone listens to whatever is going on, 24/7. However, we do not retain raw audio, video, images, or full transcripts. The system converts each interaction into a short, topic-level memory summary, stores only the minimum needed context, and deletes the source content after processing. Raw audio, video, images, and transcripts never leave the user’s device. They are processed locally, compressed into short topic-level summaries, and then deleted. Only the minimum necessary summary or task-specific instruction is shared with an external agent, and only when the user approves or triggers an action.

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
