# Copy-paste prompts for Claude (artifacts / design)

How to use: **first attach `DESIGN_BRIEF.md`** (or paste it), then send one prompt below.
Build them in order — Screen 1 is the hero and sets the visual system the rest reuse.
After the first artifact looks right, prompt 5 locks the system so the others match.

---

## Prompt 1 — Live Demo Dashboard (the hero)

```
Using the attached DESIGN_BRIEF.md, design the Live Demo Dashboard as a single
self-contained React + Tailwind artifact.

This is a real-time view of a smart-glasses agent that hears conversations and
creates calendar events. Lay it out as a 3-stage horizontal pipeline with a
visible flowing connection between stages:

  [ LISTENING ]  →  [ CLAUDE THINKING ]  →  [ CALENDAR ]

- LISTENING (left): a live, reacting audio waveform/pulse in cyan, a "Listening…"
  label, and a stream of transcript lines appearing in monospace as they're "heard."
- CLAUDE THINKING (center): when a transcript implies a plan, show a card that reveals
  Claude's decision — the tool name (e.g. create_calendar_event) and the extracted
  fields (title, time, participants) in monospace, like structured output forming.
- CALENDAR (right): finished event cards materialize with a satisfying pop + mint glow.
  Show "Dinner with Alex · Tomorrow 7:00 PM" style cards stacking newest-on-top.

Animate the whole flow on a loop using hardcoded data + setTimeout so it plays like a
live demo: hear → think → create, staggered, eased, ~400ms transitions. Include at
least one CREATE, one CANCEL (event greys out + strikethrough), one TASK (checklist
item), and one "nothing actionable" line that softly dismisses.

Dark mode, glassmorphism cards, indigo→cyan accent, lots of negative space, premium and
calm. Make motion the personality. It must look impressive on a projector from across a room.
```

---

## Prompt 2 — Today / Agenda view

```
Using the same visual system as the dashboard, design a "Today" agenda screen: the
calendar the glasses agent has been quietly filling.

A clean vertical timeline of the day with event cards the agent created. Each card
shows title, time, duration, participants, and a tiny "captured by glasses 🎙️" tag with
a relative timestamp ("2m ago"). Mix event types: Coffee, Study Session, Dinner with Alex,
a Call, plus one Google Task (a to-do without a time, shown distinctly with a checkbox).

Show one event in a "cancelled" state (struck through, dimmed) and one freshly-created
event still glowing. Dark mode, glassmorphism, indigo→cyan, generous spacing. Glanceable
and premium — Linear/Apple energy, not a busy SaaS calendar.
```

---

## Prompt 3 — Landing / hero splash

```
Using the same visual system, design a single landing/hero screen for this project,
suitable for a Devpost header and the intro slide of a live demo.

Center the headline "Your calendar, handled by your glasses." with a one-line subhead
explaining it passively listens to conversations and creates calendar events
automatically. Include a sleek rendering or stylized icon of smart glasses, and a
compact 3-step pipeline graphic: Listen → Understand → Schedule (mic → brain → calendar)
with the flowing-particle connector. Dark, cinematic, lots of negative space, one tasteful
indigo→cyan gradient glow. Minimal — it should feel like a premium hardware product page.
```

---

## Prompt 4 — Glasses HUD overlay (stretch)

```
Using the same visual system, design a first-person "glasses HUD" view: what the wearer
sees through the Ray-Ban Meta lenses. A softly blurred real-world scene (two people at a
cafe) with a minimal AR overlay in a corner: a small frosted confirmation toast that reads
"✓ Dinner · Tomorrow 7:00 PM — added" fading in. Keep the overlay sparse, elegant, and
unobtrusive — high-end AR, not a cluttered game HUD. Same indigo→cyan + mint success accent.
```

---

## Prompt 5 — Lock the design system (run after Screen 1 looks right)

```
From the dashboard you just made, extract a reusable design system so every screen matches.
Output: exact color tokens (hex), the type scale and fonts, card/glassmorphism specs
(blur, border, radius, shadow), the accent gradient, spacing scale, and the standard
animation timings/easing. Present it as a tidy spec I can paste into each subsequent prompt.
```

---

### Tips
- If a result feels too "SaaS dashboard," reply: *"more negative space, fewer elements,
  make it feel like premium hardware — Apple/Linear, not a data dashboard."*
- To push motion: *"make the data visibly flow between the three stages; add a particle
  stream along the connectors."*
- To get demo-ready: *"loop the animation so it auto-plays for a 60-second demo without
  interaction."*
- Iterate one screen to perfect before generating the rest — consistency comes from
  reusing the locked system (Prompt 5), not regenerating from scratch.
