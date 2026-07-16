# 20 — Conversation context: a dialogue thread the brain can follow

Status: ready-for-agent

## What to build

A bounded, in-session working memory so follow-ups have a referent ("no, the other one", "close that", "do the same for D:"). Distinct from long-term markdown memory (issue 07), which already works and is untouched.

**What already exists — build on it, don't duplicate it:** `ClaudeCodeBrain` and `GrokCliBrain` both retain `session_id` and pass `--resume`, so the brain already remembers *its own* previous turns within a session. The real gap is twofold:

1. **Reflex-handled turns never enter the brain's thread.** "play dhurandar" (reflex) → "pause that" (brain): the brain never saw turn one. The brain's resumed session has holes wherever a reflex answered.
2. **Nothing manages the thread's lifecycle** — sessions resume forever (stale context days later), and there's no shared transcript for the fake/other brains or for tests.

Design:

- **`jarvis/dialogue.py` — a `DialogueThread`**: ring buffer of the last N turns (default ~8), each turn = (utterance, who answered: reflex/brain/offline, spoken reply, action taken ok/failed, timestamp). Owned by the resident loop / `handle_command` caller; threaded through `handle_command` like `bus` is today.
- **Every tier appends** its turn — reflexes, offline commands, and brain turns alike (append at the same seam where audit logging already happens, to avoid a second scatter of call sites).
- **Brain prompt injection:** when a turn escalates to the brain, prepend a compact "recent exchanges" digest of turns the brain has NOT seen (i.e. reflex/offline turns since the last brain turn) to the command text. Claude's `--resume` keeps its own turns; the digest only fills the holes. For Grok/fake, same mechanism, same digest. Keep the digest terse — token budget matters (user hits Claude limits).
- **Staleness reset:** if the gap since the last turn exceeds a threshold (settings key, default ~10 min), clear the thread AND call `brain.reset_session()` — a fresh conversation, like a person walking back into the room.
- The thread is also the natural seat for issue-19 synergy: the digest may include the last observed state line if an observe call happened (cheap, optional).

## Scope

In: `DialogueThread`, appends from all tiers, digest injection for brain turns, staleness reset (settings key `dialogue_stale_minutes` / env), tests.
Out: persistence across daemon restarts; long-term memory changes; UI display of the thread; changing reflex behavior (they stay context-free — a clean "pause" needs no thread).

## Acceptance criteria

- [ ] "play dhurandar" (reflex) then "pause that thing" (brain) → the brain's prompt contains the dhurandar turn; verified via args-inspection on a fake CLI
- [ ] Brain-answered turn followed by another brain turn does NOT re-inject already-seen turns (no digest bloat on consecutive brain turns)
- [ ] After `dialogue_stale_minutes` of silence, the next turn starts a fresh thread and a fresh brain session (`reset_session` called)
- [ ] Thread is bounded: turn 9 evicts turn 1; digest stays under a small fixed token budget
- [ ] Reflex-only sessions never spawn a brain process just to record context
- [ ] Full suite green and quota-safe (no real Claude calls in default run)

## Test plan

- Unit: `DialogueThread` append/evict/staleness/digest formatting
- Unit: `handle_command` appends for reflex, offline, and brain paths (fakes)
- Integration: fake Claude CLI captures argv/prompt → assert digest contents for the reflex→brain handoff case; assert absence for brain→brain
- Regression: memory reflex, confirm gate, compound gate all unaffected (digest rides inside the brain command string only)

## Blocked by

— (independent of 19; both can land in either order)

## User stories covered

None — v1.2 "make it smart" wave (working-memory gap identified 2026-07-13 live testing)
