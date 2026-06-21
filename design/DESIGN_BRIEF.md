# Design Brief — Glasses Agent

> Attach or paste this whole file as context when prompting Claude to generate UI.
> It is the single source of truth for *what the product is* and *how it should look*.

## 1. What it is (the pitch)
Smart glasses that **passively listen to your real-world conversations and quietly
put your life on your calendar.** You say "let's grab dinner at 6 tonight" out loud
to a friend — a few seconds later it's a Google Calendar event. No phone, no typing,
no "hey assistant." It just hears the plan and handles it.

One-liner for the hero: **"Your calendar, handled by your glasses."**

## 2. How it works (the pipeline — this IS the demo)
```
🎙️  Mic (Ray-Ban Meta / laptop)
      │  raw audio
      ▼
🌊  Deepgram (nova-3)        → live speech-to-text
      │  transcript text
      ▼
🧠  Claude (haiku-4-5)        → decides: is this an action? which tool?
      │  tool call
      ▼
📅  Google Calendar / Tasks   → event created / cancelled / rescheduled
```
Claude has 4 "tools" it can choose: **create event, cancel event, reschedule event,
create task.** It also decides to do *nothing* for vague talk ("we should hang sometime").

The magic to visualize: **the gap between hearing and acting is automatic and invisible.**
The UI should make that pipeline feel alive and intelligent.

## 3. Who's watching
Hackathon judges + a live demo on a projector. So: legible from across a room, looks
impressive in motion, tells the pipeline story in one glance.

## 4. The screens to design
1. **Live Demo Dashboard (HERO — build this first).** Real-time view of the pipeline:
   listening state, live transcript streaming in, Claude's decision appearing as a card,
   the calendar event materializing. This is what runs on screen during the demo.
2. **Today / Agenda view.** The calendar the agent has been quietly filling — clean,
   glanceable, shows events with the little detail Claude inferred (title, time, people).
3. **Landing / hero splash.** One screen for the Devpost & intro slide. The pitch line,
   a glasses visual, the 3-step pipeline.
4. *(stretch)* **Glasses HUD overlay.** First-person AR-style view: what the wearer
   "sees" — a subtle confirmation toast floating in the corner when an event is captured.

## 5. Visual direction
**Mood:** futuristic, calm, premium hardware. Apple x Linear x a16z. NOT a busy SaaS
dashboard. Lots of negative space. Motion is the personality.

**Theme:** dark mode primary. Near-black background, not pure black.

**Palette (suggested — refine freely):**
- Background: `#0A0A0F` → `#0E0E16` (subtle vertical gradient)
- Surface / cards: `#16161F` with 1px `#262633` border, soft glassmorphism blur
- Primary accent: electric indigo→cyan gradient `#6366F1 → #22D3EE`
- Success (event created): mint `#34D399`
- Warning (cancel): amber `#FBBF24`
- Text: `#F5F5F7` primary, `#8A8A99` secondary
- "Listening" pulse: cyan glow

**Typography:**
- UI / headings: Inter or Geist (tight tracking on big headings)
- Transcript + agent "thinking" + tool calls: a monospace (Geist Mono / JetBrains Mono)
  — the mono font sells the "machine intelligence" feel. Use it for anything the system
  is *processing*.

**Signature visual elements:**
- A **live audio waveform / pulse** that reacts while listening (the heartbeat of the app).
- **Glassmorphism cards** (frosted, subtle — a nod to "glasses").
- A **flowing connector / particle stream** between the 3 pipeline stages, so data
  visibly "moves" from mic → brain → calendar.
- Cards **animate in** (fade + slide + slight scale) as decisions happen. Stagger them.
- Subtle glow/bloom on active elements. Tasteful, not neon-gamer.

**Motion principles:** everything eases in (cubic-bezier, ~400ms). Listening = gentle
infinite pulse. New event = satisfying pop + glow that settles. Nothing janky or instant.

## 6. Real data shapes (use these in mockups so it feels true)
Transcript utterance: `"yeah let's grab dinner tomorrow at 7, sounds good"`

Claude decision (a tool call):
```json
{
  "tool": "create_calendar_event",
  "title": "Dinner",
  "event_type": "dinner",
  "start_iso": "2026-06-21T19:00:00-07:00",
  "participants": ["Alex"]
}
```
Resulting event card: **Dinner with Alex · Tomorrow 7:00 PM · 1 hr**

Other states to show: a **cancel** ("rain check" → event greys out / strikes through),
a **task** ("remind me to email Sam" → checklist item, not a calendar block), and a
**"nothing actionable"** quiet state ("we should hang sometime" → soft dismissed chip).

## 7. Tech for the generated artifact
React + Tailwind, single file, self-contained. Use mock/hardcoded data + setTimeout to
fake the live stream (no real backend needed for the design). Framer-motion-style
animation feel (or CSS transitions). Make it run as a standalone artifact.
