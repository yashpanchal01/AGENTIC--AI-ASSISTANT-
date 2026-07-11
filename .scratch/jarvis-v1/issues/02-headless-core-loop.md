# 02 — Headless core loop: text → persistent tiered brain → act → Piper

Status: done

## What to build

The first shippable JARVIS path with no overlay: accept a command as text, run it through a provider-swappable Brain adapter (fake brain in tests, real Claude Code headless in smoke), apply tiered autonomy (safe tools auto-run with zero prompts; destructive/outward/system denied or ask-first; secrets never), keep **one persistent conversation** across commands, perform real safe-tier actions (files in approved folders, app launch, read-only terminal, Q&A/web), and speak the reply with local Piper.

This is the automated test seam: `handle_command(transcript_text) → reply + actions taken`. Prefer external-behavior assertions with a fake Brain; a small number of smoke tests may hit the real Claude CLI. Prototype validation lives in `jarvis-proto/` (throwaway evidence only — delete that folder once this real loop is green). Invocation shape that beat prose in the prototype: headless stream-json, allowedTools for safe tier, permission-mode for safe tier, append-system-prompt for "act, don't ask", resume/session for persistence. Sandbox must allow GUI app launches in the safe tier.

New project: Python (`py -3.13`), separate from LocalFlow (copy patterns only; never modify LocalFlow).

## Acceptance criteria

- [x] Typed or injected transcript produces a spoken Piper reply end-to-end in a terminal (no UI)
- [x] Safe-tier actions run with zero permission prompts; risky tiers do not auto-run
- [x] One long-lived agent session carries context across commands (e.g. correction-style follow-ups work)
- [x] `handle_command` is covered by automated tests using a fake Brain; at least one optional real-CLI smoke path documented
- [x] Provider adapter exists so the brain is not hard-coded forever to one vendor
- [x] `jarvis-proto/` removed or clearly marked deleted after the real loop is verified

## Blocked by

None - can start immediately

## User stories covered

9–11, 14–19, 29–34, 42–43 (plus testing decisions in the PRD)

## Comments
