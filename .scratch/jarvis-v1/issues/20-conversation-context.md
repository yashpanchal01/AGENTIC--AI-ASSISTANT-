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

## Comments

### 2026-07-16 — implemented (agent, left in tree for review; not committed)

New module `jarvis/dialogue.py` (`DialogueThread` + frozen `DialogueTurn`),
threaded through `handle_command` as an optional `dialogue=` kwarg. Summary:

- **One seam, no scatter:** appends ride the existing audit seam —
  `_audit_result` grew optional `dialogue`/`utterance` params and calls a new
  `_record_dialogue` helper, so every tier's outcome is recorded exactly once
  at the same places audit records already fire. The confirm-gate return in
  `handle_command` (which had no `_audit_result` of its own) got an explicit
  `_record_dialogue(..., path="confirm")`. `handle_confirmation` and
  `LongTaskService` internals were NOT given the thread (their `_audit_result`
  calls pass no dialogue), so a turn can never double-append.
- **Tier mapping:** paths brain/long_task/confirm → tier `"brain"`
  (`"offline"` when `error == "brain_unreachable"`); everything else →
  `"reflex"`. `path="empty"` turns are skipped (nothing was said).
- **seen_by_brain, not just tier:** the digest boundary is the last turn the
  brain process actually *received*, not the last brain-tier turn. Local
  denies (secrets), declined/incomplete confirmations, unreachable/cancel/busy
  and CLI-not-found turns never spawn a CLI, so they stay digest-visible
  (`_BRAIN_NEVER_SAW` set in core). Deviation from the naive "since last brain
  turn" reading of the spec — otherwise "play X" (reflex) → "delete Y"
  (declined) → "pause that" would silently lose the reflex context.
- **Digest injection point:** `brain_text = dialogue.compose_brain_command(text)`
  is computed once near the top of `handle_command` (from PRIOR turns only)
  and used at the foreground `ask_brain`, the main `long_tasks.handle_brain`,
  and passed into `handle_confirmation` so the confirmed re-ask still carries
  it (the propose turn was answered locally without spawning the CLI). The
  early cancel/busy long-task path deliberately keeps the raw text —
  `is_cancel_utterance` matches exact phrases and a digest prefix would break
  cancel routing. The spoken/recorded utterance is always the raw text.
- **Digest format (token-tight):** header + `- user: "…" -> tier: "…" (ok|failed)`
  per unseen turn + footer; utterance/reply whitespace-collapsed and truncated
  to 80 chars, ring capped at 8 turns → worst case ~1.5 KB (test-asserted
  < 1800 chars). Empty string on consecutive brain turns (no bloat;
  `--resume` covers the brain's own turns).
- **Staleness:** checked once per command at the top of `handle_command`;
  `reset_if_stale()` clears the thread and, when true, core calls
  `brain.reset_session()` (id drop only — never spawns a process, so
  reflex-only sessions stay brain-free). Threshold from new
  `JarvisConfig.dialogue_stale_minutes` (default 10) / env
  `JARVIS_DIALOGUE_STALE_MINUTES` / settings key `dialogue_stale_minutes`
  (non-positive or non-numeric values ignored). `DialogueThread.now` is
  injectable for tests.
- **Ownership/wiring:** like `audit`, the caller owns the thread —
  `FrontDoorSession` gets a `dialogue` field (lazily created like
  `long_tasks`; `run_daemon` passes one built from config), the REPL creates
  one per session (`:new` clears it alongside `reset_session`), and
  `run_listen`/`listen_and_handle`/`run_armed_pipeline`/overlay lifecycle all
  pass it through. `run_once` stays dialogue-free (one turn per process —
  nothing to remember). Issue-19 observe-state line in the digest: not done
  (spec marked it optional); observe calls happen inside the brain's own
  MCP turn, so `--resume` already covers them.
- **Backgrounded long tasks:** recorded with the "On it." ack reply; the
  eventual final reply is not retro-patched into the thread (kept simple —
  the brain saw its own turn anyway via resume).
- **Tests:** 415 passed / 13 deselected before → 431 passed / 13 deselected
  after (16 new in tests/test_dialogue.py), quota-safe: brain turns run
  against FakeBrain (args-inspection via `_history`) or a monkeypatched
  `subprocess.Popen` fake Claude CLI emitting one stream-json result line
  (argv-level proof, including `--resume` retention).
- **Verified injected prompt** (scripted scenario, fake CLI `-p` argument
  after "play dhurandar" reflex turn, 0 CLI spawns on the reflex turn):

  ```
  [Recent exchanges JARVIS handled locally (you did not see these):
  - user: "play dhurandar" -> reflex: "Playing Dhurandar on Spotify." (ok)
  The user now says:]
  pause that thing
  ```

  The following "resume the music" brain turn spawned with prompt exactly
  `resume the music` plus `--resume sess-demo` — no re-injection.
