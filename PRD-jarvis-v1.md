# PRD — JARVIS v1

A Windows-first, voice-driven AI assistant for one person's PC. Say "Jarvis, …" from anywhere → it acts (files, apps, terminal, email, music) with zero permission clicking for safe actions → answers back in a natural voice, through a slick native overlay.

Source of truth: the JARVIS v1 shared-understanding document (design interview complete, all decisions locked, prototype findings validated 2026-07-11).

## Problem Statement

I spend my day at a Windows PC doing small, constant chores by hand: hunting for files, opening apps and folders, checking email and my calendar, controlling music, running quick terminal tasks, looking things up. Each one is trivial, but each one costs a context switch — hands off what I'm doing, find the window, click through it, come back.

Existing "assistants" don't solve this for me:

- Windows' built-in voice tools are unreliable on my machine and can't actually *do* multi-step work.
- Cloud assistants (phone-style) can't touch my files, my terminal, or my apps.
- AI chat windows can reason, but I have to type at them, babysit them, and click "allow" on every single action — which defeats the point of an assistant.
- Anything always-listening or that silently does destructive things is a non-starter: I want to trust exactly when it hears me and exactly what it's allowed to do on its own.

I want to speak a request from anywhere in the room and have it *done* — safely, predictably, without a wall of permission prompts — and hear the answer back in a pleasant voice, on hardware I already own, at zero extra cost beyond the AI subscription I already pay for.

## Solution

JARVIS v1 is a small always-running Windows app that turns my voice into real actions on my PC:

1. I say **"Jarvis"** (or press a fallback hotkey). Nothing is ever streamed anywhere until that moment — wake-word detection is fully local.
2. It records until I stop talking, transcribes my speech **locally on my GPU**, and hands the raw text to a **frontier-class AI brain** (Claude Code running headless, covered by my existing subscription).
3. The brain decides and **acts**: finds and organizes files, launches apps, runs terminal work, answers questions from the web, reads my Gmail and Calendar (read-only), controls Spotify.
4. **Safe actions run instantly with zero prompts.** Anything destructive, outward-facing, or system-level gets asked about first. Secrets are never touched, period.
5. It **replies aloud** in a natural local voice (Piper) and shows its state the whole time in a minimal, native "Aurora-style" overlay: armed → heard → working → speaking.
6. It keeps **one continuous conversation**, so "actually, close it instead" just works, and it keeps **long-term memory as plain markdown notes** I can read and edit myself.

It starts with Windows, sits quietly until called, logs everything it does, and degrades gracefully: if the internet drops, it tells me its brain is unreachable instead of hanging. It is honest about speed — a capable butler that takes roughly 7–20 seconds per request, not a movie AI with instant banter.

## User Stories

### Waking JARVIS and talking to it

1. As a user, I want to say the whole thing in one breath — "Jarvis, open my downloads folder" — so that quick commands take a single utterance with no extra steps.
2. As a user, I want to be able to just say "Jarvis", get an acknowledgment (a beep and the overlay switching to its armed state), and *then* speak my command, so that I can gather my thoughts before longer or more careful requests.
3. As a user, I want the wake word to be required before every single command — no open-mic follow-up window — so that JARVIS is completely predictable about when it is and isn't listening.
4. As a privacy-conscious user, I want wake-word detection to run entirely locally on my machine, so that no audio ever leaves my PC before I have deliberately woken the assistant.
5. As a user, I want JARVIS to notice when I've stopped speaking and end the recording on silence, so that I never have to press or say anything to finish a command.
6. As a user, I want a push-to-talk hotkey as a fallback input, so that I can still command JARVIS when the room is noisy, the mic is misbehaving, or the wake word won't trigger.
7. As a user, I want the hotkey path to flow through exactly the same pipeline as the wake-word path, so that both ways of talking to JARVIS behave identically.
8. As a user, I want the proper nouns I use often (project names, tool names) to be transcribed correctly via a tunable dictionary/hotwords list, so that "Claude Code" doesn't become "broadcourt" and derail my command.

### File operations

9. As a user, I want to ask JARVIS to find files by voice ("Jarvis, where's that PDF about invoices from last week?"), so that I don't have to dig through Explorer myself.
10. As a user, I want JARVIS to create, move, rename, and organize files inside my approved folders with zero permission prompts, so that routine tidying is genuinely hands-free.
11. As a user, I want JARVIS to open a file and summarize or read its contents aloud, so that I can check a document without switching away from what I'm doing.
12. As a user, I want JARVIS to ask me first before deleting or overwriting anything, so that irreversible mistakes can't happen autonomously.
13. As a user, I want JARVIS to ask me first before touching anything outside my approved folders, so that the blast radius of hands-free mode is always bounded by folders I chose.

### Apps and terminal

14. As a user, I want to launch GUI applications by voice ("Jarvis, open Spotify") with no permission prompt, so that opening an app by voice is as fast as it should be.
15. As a user, I want to ask JARVIS to close or switch applications, so that I can manage my workspace without touching the mouse.
16. As a user, I want JARVIS to run terminal work for me by voice, with safe read-only commands executing automatically, so that quick checks ("how much disk space is left?") are instant and prompt-free.
17. As a user, I want any risky or system-level command (installs, service changes, shutdowns, registry edits) to require my explicit go-ahead first, so that JARVIS can never reconfigure my system on its own.

### Questions and the web

18. As a user, I want to ask JARVIS general questions and get a spoken answer, so that I have a knowledgeable assistant on tap without opening a browser.
19. As a user, I want JARVIS to look things up on the web when a question needs current information, so that its answers aren't limited to what the model already knows.

### Gmail (read-only)

20. As a user, I want to ask "Jarvis, any new email?" and hear a short spoken summary of what's unread, so that I can triage my inbox without opening it.
21. As a user, I want to ask JARVIS to search my inbox or summarize a specific thread aloud, so that I can catch up on a conversation hands-free.
22. As a user, I want JARVIS's email access to be strictly read-only — it declines to send, reply, or forward even if I ask — so that there is zero risk of anything going out under my name in v1.
23. As a user, I want to sign in to Google once via OAuth (covering both Gmail and Calendar), with tokens stored securely and never in JARVIS's readable memory notes, so that setup is one-time and my credentials stay out of reach.

### Calendar

24. As a user, I want to ask "Jarvis, what's on my calendar today?" and hear my schedule, so that I can plan my day without opening a calendar app.
25. As a user, I want to ask about my next event or whether a given time is free, so that scheduling questions get answered while I keep working.

### Spotify

26. As a user, I want to play, pause, resume, and skip music by voice, so that music control never interrupts what my hands are doing.
27. As a user, I want to ask for a specific song, artist, or playlist by name, so that "Jarvis, play some lo-fi" just works.
28. As a user, I want to ask what's currently playing and adjust the volume by voice, so that all everyday music control lives in JARVIS.

### Corrections and conversation context

29. As a user, I want to interrupt or redirect with "actually, …" ("actually, close it" / "actually, put it in the other folder") and have JARVIS understand relative to what it just did, so that fixing course doesn't require restating everything.
30. As a user, I want follow-up references like "it", "that file", or "the same folder" to resolve correctly within a conversation, so that talking to JARVIS feels like talking to a person who was paying attention.
31. As a user, I want JARVIS to hold one continuous conversation rather than treating every command as a blank slate, so that context carries across commands within a session.

### Tiered permissions and safety

32. As a user, I want safe actions — read-only operations and reversible changes inside my approved folders — to auto-run with literally zero prompts or clicks, so that the assistant is actually autonomous where it's safe to be.
33. As a user, I want destructive, outward-facing, or system-level actions to always be asked about first, with JARVIS waiting for my explicit confirmation, so that autonomy never crosses into risk without me.
34. As a user, I want JARVIS to never touch secrets — no reading, storing, or speaking passwords, API keys, or credentials, under any tier — so that a voice assistant can never become a security hole.
35. As a user, I want to configure which folders count as "approved" for autonomous action, so that I control exactly where hands-free mode applies.
36. As a user, I want my preferences (hotkey, approved folders, voice) kept in a simple settings file, so that I can adjust JARVIS without editing code.

### Overlay and state feedback

37. As a user, I want the overlay to clearly show when JARVIS is armed and listening, so that I always know whether the mic is hot.
38. As a user, I want to see what JARVIS *heard* (the transcript) on the overlay, so that I can catch a mis-transcription before or while it acts.
39. As a user, I want an unmistakable "working" state during the several seconds JARVIS is thinking and acting, so that I never wonder whether it heard me or died.
40. As a user, I want the overlay to indicate when JARVIS is speaking its reply, so that its lifecycle is visible from start to finish.
41. As a user, I want the overlay to be a slick, minimal, native window that floats above my work without stealing focus — not a browser tab or web app — so that JARVIS feels like part of the OS, not a webpage.

### Natural voice replies

42. As a user, I want replies spoken in a natural, pleasant local voice that responds instantly and works offline, so that hearing JARVIS is enjoyable and never depends on the network.
43. As a user, I want spoken replies to be concise — an answer, not an essay read aloud — so that voice interaction stays faster than reading a screen.

### Long-running tasks

44. As a user, I want a long, multi-step task to keep running in the background while I do other things, with the overlay showing it's still working, so that I'm not held hostage by the assistant's runtime.
45. As a user, I want a spoken announcement when a long task finishes (or fails), so that I can fire-and-forget a request and trust I'll hear the outcome.

### Memory

46. As a user, I want to say "Jarvis, remember that …" and have that fact persist across sessions and reboots, so that JARVIS accumulates useful knowledge about me and my machine.
47. As a user, I want long-term memory stored as plain markdown notes — dated, tagged, summarized — that I can open, read, edit, and delete myself, so that JARVIS's memory is never a black box.
48. As a user, I want credentials and secrets to be categorically excluded from those memory notes, so that a human-readable memory file can never leak anything sensitive.
49. As a user, I want JARVIS to actually use remembered facts in later sessions without me repeating them, so that memory pays off rather than just existing.

### System lifecycle

50. As a user, I want JARVIS to start automatically with Windows, so that it's simply always available without me launching anything.
51. As a user, I want JARVIS to warm up its brain at startup, so that my first command of the day doesn't pay an extra ten-second cold-start penalty.
52. As a user, I want a system tray icon showing JARVIS is alive, with a way to pause or quit it, so that I can always see and control whether it's running.
53. As a user, I want an audit log of every action JARVIS has taken, so that I can review after the fact exactly what my autonomous assistant did and when.

### Errors and degradation

54. As a user, I want errors explained aloud in plain language ("I couldn't find that file"), so that failure is a conversation, not a stack trace or a frozen overlay.
55. As a user, I want JARVIS to say so when it can't or won't do something (and why), so that nothing ever fails silently.
56. As a user, I want JARVIS to detect when the internet is down and tell me aloud that its brain is unreachable — while wake word, transcription, and voice stay working locally — so that offline means graceful degradation, not a hang.
57. As the owner of a modest GPU, I want JARVIS to be frugal with video memory and to coexist with games and other GPU-heavy apps, so that having an assistant resident doesn't cost me my machine's other uses.

## Implementation Decisions

All of the following are locked outcomes of the design interview and the validated prototype; a build session should start from them without re-litigating.

- **Pipeline.** Wake word (local) → record until silence → faster-whisper speech-to-text (local, GPU) → Claude Code headless as the brain (cloud, makes decisions and performs actions) → Piper text-to-speech (local) → native overlay showing state throughout.
- **Permission policy: tiered autonomy.** Read-only and reversible actions inside approved folders auto-run with zero prompts; destructive, outward-facing, and system-level actions require asking first; secrets are never touched at any tier. The tiers map directly onto the brain's allowed-tools configuration — the prototype verified genuinely zero-prompt operation for the safe tier, so the policy is pure configuration, not custom enforcement code.
- **Brain: Claude Code headless, behind a provider-swappable adapter.** Free on the existing subscription, frontier-level reasoning, and it performs real tool work natively. The adapter means swapping to another provider later is a configuration change, not a rewrite. The prototype validated the exact invocation shape (the one place a precise shape beats prose): headless invocation with `--output-format stream-json --verbose`, `--allowedTools <safe-tier list>`, `--permission-mode` for the safe tier, `--append-system-prompt` for the JARVIS persona ("act, don't ask"), and `--resume <session-id>` for conversation persistence.
- **One persistent agent conversation — never spawn per command.** The prototype proved cold start adds roughly 10–12 seconds to the first command only, and that session resume carries context across commands (corrections like "actually, close it" work). v1 must therefore keep a single long-lived agent conversation (Agent SDK or session-resume) for the assistant's lifetime.
- **Sandbox must allow GUI app launches in the safe tier.** Headless Claude's default sandbox blocks launching GUI applications; the prototype validated that permitting app launches in the safe-tier configuration fixes this. v1's configuration must include it.
- **Input: wake word required every time.** No open-mic follow-up window — the user explicitly chose predictability over convenience. A push-to-talk hotkey is the fallback. The detector will be openWakeWord or Porcupine (which ships a prebuilt "jarvis" keyword but needs a free Picovoice key); the choice is decided by a standalone A/B bench test on the actual mic before anything is wired together. Explicitly rejected: Windows SAPI (broken on this machine) and browser speech recognition (blocked in Brave, online-only — it was prototype scaffolding, nothing more).
- **Integrations for v1: Gmail read-only + Spotify, with Calendar coming free via the same Google OAuth.** Files, apps, terminal, and web questions come free with the brain and need no integration work. Sending messages of any kind is explicitly not v1 (outward-facing risk).
- **App technology: Python with a PySide6 native overlay, as a brand-new separate project.** JARVIS copies LocalFlow's proven parts — mic capture, faster-whisper setup and dictionary, and the "Aurora Mono" overlay painting approach — but LocalFlow itself is never modified. No web, browser, or Electron UI (user veto). QML is the designated upgrade path if the native overlay's animations feel stiff.
- **Voice out: Piper.** Local, effectively instant, free, and the user already downloaded a voice (~60 MB) and likes it. Kokoro (better quality, ~1 GB RAM) or ElevenLabs (best, paid) are one-function swaps later, not v1.
- **Memory: markdown notes plus retrieval.** Dated and stable notes with tags and summaries, human-editable, with credentials categorically excluded. Within a conversation, the persistent Claude session covers short-term context; markdown memory is for facts that must outlive sessions.
- **No transcript-polish model.** Raw whisper output goes straight to the brain. Commands are intent, not dictation — Claude decodes messy transcripts fine, and skipping an Ollama polish step frees scarce VRAM.
- **Hard constraints.** Windows 11; RTX 4050 with 6 GB VRAM shared between whisper and everything else; 8 GB system RAM; Python invoked as `py -3.13` (bare `python` resolves to the wrong version on this machine); cost ceiling of $0 beyond the existing Claude subscription.
- **Latency expectations are locked as honest.** Roughly 7 seconds for a simple command and 15–20 seconds for multi-step work (the brain batches steps, so step count barely multiplies time or cost). This is acceptable for a butler; no design decision may assume or promise faster.
- **Build order.** (1) Wake-word A/B bench test standalone; (2) core loop headless in a terminal, no UI — wake → record → whisper → persistent tiered-permission brain → Piper; (3) overlay via the screenshot-iterate harness pattern; (4) Google OAuth (Gmail read-only + Calendar), then Spotify; (5) polish — autostart with Windows, tray icon, settings file, audit log. Each step independently testable; the project is stop-anywhere shippable.

## Testing Decisions

- **One automated seam, deliberately chosen:** `handle_command(transcript_text) → reply + actions taken` — everything between STT output and TTS input. This is where all the logic lives (intent handling, permission tiers, brain dialogue, action dispatch), and it's the part that's deterministic enough to automate.
- **Tests inject a fake Brain** through the provider-agnostic adapter, making the suite instant, free, and repeatable. A small number of smoke tests hit the real Claude CLI to prove the adapter still matches reality.
- **What makes a good test: external behavior only.** A test asserts on what a transcript produces — the reply text and the actions taken — never on implementation details (which internal functions ran, what prompts looked like, how state is stored). If a refactor changes internals but behavior is identical, no test should break.
- **Fixture idea:** record `stream-json` event logs from real Claude CLI runs and replay them to drive the fake Brain, so tests exercise realistic event sequences (tool calls, partial output, session ids) without network or cost.
- **Audio components get manual bench harnesses, not automated tests.** Wake word, whisper, and Piper are hardware- and model-dependent; automated assertions there would be flaky theater. The wake-word detector choice (openWakeWord vs Porcupine) is decided by an A/B bench script measuring detection quality and latency on the actual mic.
- **The overlay is verified by a screenshot-render harness** — render the real widget states to PNGs and judge them by eye — the same screenshot → look → adjust loop LocalFlow proved out.
- **Prior art to lean on:** the jarvis-proto timing harness (latency and zero-prompt validation) and LocalFlow's scratchpad verify/render harnesses (safe imports of the real app, real-function exercise, real-widget rendering at true DPI).

## Out of Scope

- Sending email, messages, or anything outward-facing on the user's behalf.
- Always-listening ambient mode.
- Open-mic follow-up windows after a command (wake word is required every time).
- A phone app.
- Paid TTS (ElevenLabs) or Kokoro — Piper only in v1.
- The Ollama / local-LLM transcript-polish step.
- A hybrid local-model fast path for simple commands.
- Any browser, web, or Electron UI.
- Robotics of any kind.
- Multi-user support — this is one person's assistant on one PC.
- Sub-second latency promises of any sort.

## Further Notes

- **Latency honesty.** Expect ~7 s for a simple command, 15–20 s for multi-step work, plus ~10–12 s of cold start on the very first command after launch (mitigated by pre-warming at startup and keeping the session persistent). This is a capable butler, not movie banter. Every UX decision (working-state overlay, spoken acknowledgments, background long tasks) exists to make that wait feel fine.
- **Claude usage limits are shared.** JARVIS runs on the same subscription the user codes with. Heavy JARVIS use eats the same budget as normal Claude use; there is no separate metering in v1 beyond the audit log's implicit record of how often it's being used.
- **VRAM budget.** The RTX 4050 has 6 GB total. Whisper resident on GPU shares that with games and any other GPU use. Skipping the Ollama polish model is what makes this workable at all. Measure real pressure during the build; unloading the whisper model between commands is the known fallback if coexistence fails.
- **jarvis-proto is throwaway.** The prototype folder exists only as validation evidence (its notes hold the verdict). It must be deleted once the real v1 core loop runs — nothing in it is production code.
- **LocalFlow is reference-only and sacred.** It is a working, committed app the user relies on. JARVIS copies its proven patterns (mic capture, faster-whisper setup and dictionary, Aurora Mono overlay painting, the render-harness verification loop) into the new project, and must never modify the LocalFlow repo itself.
