# 14 — Local router tier (Ollama, 1B-class)

Status: ready-for-agent

## What to build

A tiny local LLM router that runs AFTER the regex reflexes miss and BEFORE the heavy cloud brain. Model: Llama-3.2-1B-Instruct Q4_K_M via Ollama as primary; Qwen2.5-0.5B-Instruct as fallback if RAM pressure demands. Strict JSON contract via Ollama structured output: `{route: "tool"|"chat"|"heavy", tool?: <name from fixed list>, confidence: 0-1}`. The router picks the tool ONLY — argument parsing stays in the existing intent handlers. `keep_alive` set so the router stays resident and never cold-starts; hard 2s timeout. Timeout, low confidence, or parse failure → escalate to the heavy brain. Offline → the router may still route to local tools and local chat (connectivity gating already exists). The router prompt carries a personal idiom table, seeded with: "close all windows" = **minimize** all windows (NOT close apps).

Why now: the audit's problem 2 — rigid regex means everyday paraphrases miss every reflex and fall into a slow, heavyweight CLI-agent call for things a 1B model can dispatch in under a second.

Hard constraints: ~0.8 GB RAM for the resident router model on this 8 GB laptop; must coexist with LocalFlow's heavy Ollama model (shared Ollama daemon, no VRAM fights with the 4 GB RTX 4050 — CPU inference is acceptable at this size); heavy thinking stays in the cloud.

## Scope

In: router module + prompt + JSON schema; wiring into `handle_command` between reflexes and brain; idiom table; eval set file (30–50 real utterances with expected routes) checked in; scoring test.
Out: argument extraction (handlers keep it); adding new tools (16 registers its own); replacing any regex reflex; Grok/Claude brain changes (issue 15).

## Acceptance criteria

- [ ] Utterances that match existing regex reflexes never reach the router (reflexes stay first)
- [ ] Router returns schema-valid JSON or the call is treated as a miss — no partial parsing
- [ ] Timeout (2s), `confidence` below threshold, or invalid JSON escalates to the heavy brain; offline escalation degrades to local tools/chat instead
- [ ] "close all windows" routes to windows-minimize-all, per the idiom table
- [ ] Eval test scores the router against the checked-in utterance set and enforces a minimum accuracy (target ≥ 90%); auto-skips when Ollama or the model is absent
- [ ] Resident router memory measured and recorded; fits the ~0.8 GB budget with LocalFlow running

## Test plan

- Unit: JSON contract parsing, confidence threshold, timeout → escalate, offline branch (Ollama client faked)
- Eval: `tests` run the routing eval set against real Ollama when present (`skipif` otherwise), report per-utterance failures
- Integration: fake brain records that escalation happened on router miss; reflex-hit path shows zero router calls
- Manual: measure RSS/`ollama ps` with router + LocalFlow model loaded; record in Comments

## Blocked by

- 13 — Land and harden the untracked apps/media/windows slices (router's tool list targets those handlers)

## User stories covered

None — backend-audit follow-up (post-v1 architecture)

## Comments
