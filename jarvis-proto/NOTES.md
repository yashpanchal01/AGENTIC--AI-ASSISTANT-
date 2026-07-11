# Verdict — jarvis-proto (2026-07-11)

**Question:** Can headless `claude -p` with pre-approved permission flags act as
JARVIS's brain with zero permission prompts, and what's the honest latency?

## Answers

1. **Permissions: SOLVED.** With `--allowedTools` + `--permission-mode acceptEdits`,
   a real file-creating action ran end-to-end with zero prompts. Tiered autonomy
   is pure configuration: safe tools in the list auto-run, everything else is
   denied rather than prompted.

2. **Latency: works, but slower than hoped, and cold-start dominates.**
   Measured (sonnet unless noted):
   - Cold first call: 11.8 s before init, **17.8 s total** for a trivial question.
   - Warm, pure question (haiku): init 1.9 s, **6.8 s total**.
   - Warm, real action (create file): init 1.9 s, first action at 4.8 s, **9.4 s total**.

   So per-command spawn costs ~2 s warm (~12 s cold), and each command re-pays it.

3. **Production implication (the real finding):** don't spawn `claude -p` per
   command. Keep ONE long-lived agent process (Claude Agent SDK, streaming input)
   that receives each transcribed utterance. That removes the respawn cost and
   keeps conversation context (follow-ups/corrections) for free. Target then
   becomes ~3–6 s per command, still not sub-second banter.

4. **Wake word:** out of scope here by design. `brain.mjs` is the module the
   wake-word front end will feed transcribed text into; this spike validates the
   brain, not the ears.

## Status

Prototype kept runnable for hands-on testing (`node jarvis-tui.mjs`).
Delete this folder once v1 development starts; lift `brain.mjs`'s event-parsing
approach into the real app (as SDK usage, not CLI spawning).
