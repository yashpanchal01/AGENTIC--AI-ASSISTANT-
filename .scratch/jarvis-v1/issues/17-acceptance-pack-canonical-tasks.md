# 17 — Acceptance pack: canonical complex tasks, end-to-end

Status: ready-for-agent

## What to build

The user's five canonical tasks as checked-in end-to-end tests — fakes wherever OS/cloud is involved, plus `os_smoke`-marked real variants where meaningful. Each test declares which tier must handle it and asserts a max-latency budget for that tier's dispatch:

| Task | Expected tier |
|------|---------------|
| (a) "open the screen recording we just captured" | router → latest-file tool (16) |
| (b) "open spotify and play the next music" | brain + tool bridge (15), two steps |
| (c) "close all the windows" → **minimize** all | router idiom (14), windows handler |
| (d) "dim my brightness to zero" | reflex (16) |
| (e) "open brave and vs code side by side, brave left 50%, vs code right" | brain + bridge: launch both, wait for windows, snap left/right |

Why now: the audit showed every one of these currently fails or falls into a 300s-class CLI call; this pack pins the target behavior so the router/bridge work is finished when these pass, and guards against regressions after.

Latency budgets (dispatch decision + local handler, fakes for cloud/OS): reflex < 1s; router path < 3s (2s router cap + handler); brain path may exceed the ~20s long-task threshold only via the existing backgrounded "on it" flow — never a silent stall.

## Scope

In: five e2e tests with fakes; tier + latency assertions; `os_smoke` real variants for (a), (c), (d); a small harness helper to run an utterance through the full reflex→router→brain pipeline with fakes injected.
Out: new features (all functionality comes from 14–16); UI assertions (issue 18); benchmark tooling beyond simple wall-clock asserts.

## Acceptance criteria

- [ ] All five tasks pass end-to-end with fakes, each handled by its declared tier (a test fails if the wrong tier answers)
- [ ] (c) minimizes windows — a test explicitly asserts no app/process is closed
- [ ] (e) with fakes: both launches issued, window-wait observed, left/right snap calls made in order
- [ ] Latency assertions enforced per tier as budgeted above
- [ ] `pytest -m os_smoke` variants for (a), (c), (d) pass on this laptop
- [ ] Pack runs in the default suite (fakes) in well under a minute

## Test plan

- The pack **is** the test plan: one test module per task, parameterized over tier expectation + budget
- Router-dependent tests reuse issue 14's skip logic when Ollama is absent (fake router responses keep the pipeline tests running everywhere)
- Manual: run the `os_smoke` variants once on this laptop and record timings in Comments

## Blocked by

- 14 — Local router tier (Ollama)
- 15 — Tool bridge (MCP)
- 16 — System controls: brightness + latest-file resolver

## User stories covered

None — backend-audit follow-up; encodes the user's canonical tasks (a)–(e)

## Comments

### 2026-07-13 — Implemented (agent)

Built the acceptance pack against `main` (router / issue 14 is shelved, so the
spec's router tier was re-mapped to the tiers that actually exist: reflex →
brain + MCP bridge, no middle tier).

Files:
- `tests/test_acceptance_pack.py` — 7 default-suite tests (fakes): (a) reflex +
  (a) paraphrase→brain, (b), (c), (d), (e), plus a (c) idiom guard.
- `tests/test_acceptance_pack_os_smoke.py` — 3 opt-in real-OS variants for
  (a)/(c)/(d).
- `jarvis/windows/intents.py` — **new (c) idiom** (see below).

Corrected tier each task actually uses (via the audit `path` that answered):
- (a) canonical "open the screen recording we just captured" → **system reflex**
  (issue-16 latest-file regex matches). Paraphrase "show me what I just recorded
  off my screen" (regex misses) → **brain + bridge** (system tool).
- (b) "open spotify and play the next music" → **brain + bridge**, 2 steps
  (apps.open → spotify.next), in order.
- (c) "close all the windows" → **windows reflex** (MINIMIZE-all).
- (d) "dim my brightness to zero" → **system reflex**.
- (e) "open brave and vs code side by side…" → **brain + bridge** (launch both,
  wait for each window, snap left then right, in order).

**(c) idiom re-homed (scope addition, forced by the shelved router):** added a
tight reflex regex `_CLOSE_ALL_WINDOWS` = `close (all|every) [the/my/your/open]
windows` in `jarvis/windows/intents.py`, checked **before** the close-focused
`_CLOSE` branch so it maps to the existing `MINIMIZE_ALL` handler (issue 13).
Verified it does NOT swallow a genuine single close: "close chrome" / "close
notepad" / "close this window" still classify as `CLOSE`. This is the only new
behavior; everything else comes from 13/15/16.

Per-criterion status:
- [x] All five tasks pass e2e with fakes, each handled by its declared tier
  (tier asserted via audit path — wrong tier fails the test).
- [x] (c) minimizes; explicit asserts that no window/app/process is closed.
- [x] (e) both launches, window-wait observed, left/right snaps in order.
- [x] Latency asserts: reflex < 1s; brain path completes inline (fakes), not
  backgrounded, no silent stall.
- [x] `pytest -m os_smoke` variants for (a)/(c)/(d) pass on this laptop
  (2.6s / 3.8s / 3.3s; suite 9.8s).
- [x] Default pack runs in ~0.5s (whole default suite 20.8s).

Test counts: default 314 → 321 (+7 pack); deselected 6 → 9 (+3 os_smoke).

Flags / deviations:
- **(c) os_smoke scoped, not global.** A faithful "close all" reflex calls a
  GLOBAL minimize-all that would minimize the user's whole desktop. The real-OS
  variant drives the real idiom + handler but injects a minimize-all op scoped
  to a Notepad window WE spawned, asserts that window minimizes and its process
  survives (nothing closed), then restores/closes it. Global routing is covered
  by the fakes suite.
- **(b) compound routing.** With the full reflex stack wired, the `apps` reflex
  would match "open spotify …" (its `resolve_app` accepts a `spotify …` prefix)
  and launch Spotify only — dropping the "play next" half. That compound-vs-
  reflex routing is a routing-tier concern (shelved issue 14), out of scope for
  17. Following the existing bridge-scenario convention, (b)/(e) run the
  brain-path (bridge engaged) to pin the target two-step behavior; the tier
  assertion still guards that the brain — not a half-doing reflex — answers.
- (d) os_smoke honors the canonical "to zero": it drives real WMI to 0 (brief
  screen dip), captures the original first and ALWAYS restores in `finally`.
  Skips on panels without WMI brightness.

### 2026-07-13 — Compound-command guard (closes the (b)/(e) gap above, agent)

The flag above ("(b) compound routing … out of scope for 17") is now CLOSED: the
half-execution it described is fixed at the reflex layer, so (b)/(e) route to the
brain through the GENUINE stack rather than a forced brain-path shim.

Files:
- `jarvis/compound.py` — **new.** `is_compound_command(text) -> bool`,
  conservative (biased to False). Triggers on either shape:
  1. a conjunction (`" and "`, `" then "`, `", then "`, `"; "`, `" & "`,
     `" after that "`) followed by a second imperative action verb starting a
     new command (play/pause/resume/stop/skip/next/previous/open/launch/start/
     run/close/minimize/maximize/snap/move/put/set/dim/turn/mute/focus/switch/
     show/delete/send). A verb whose object is a back-reference pronoun
     ("… and play **it**/**them**") is a continuation, NOT a new action, so it
     does not trigger — this is what keeps media "find X and play it" single.
  2. a two-window arrangement: "side by side" / "split screen" / "next to each
     other", OR an explicit LEFT placement paired with an explicit RIGHT
     placement ("brave left 50%, vs code right"). One side alone (a single snap)
     never triggers.
- `jarvis/core.py` — one gate in `handle_command`, placed AFTER the memory
  reflex (single-fact "remember … and …" stays local) but BEFORE Google / apps /
  system / media / windows / spotify. When `is_compound_command` is True every
  reflex below is skipped (guarded with `and not compound`) and the command
  routes to the brain + MCP bridge; offline it falls to the existing
  BRAIN_UNREACHABLE path — never a silent half-execute.
- `tests/test_compound.py` — **new**, 36 unit cases: every must-pass positive
  and must-not-break negative from the task, plus edges.
- `tests/test_acceptance_pack.py` — (b)/(e) now wire the FULL reflex chain (the
  same apps/spotify/windows handlers back both the reflex tier and the bridge);
  the tier assertion proves the reflexes DECLINE and the brain composes the
  two/four steps. Added two guard tests: a single "open spotify" still lands on
  the apps reflex (guard is one-sided), and a compound command offline degrades
  to `brain_unreachable` with the apps reflex never firing.

Placement rationale: memory is the only tier that legitimately swallows an "and"
(a single fact), so the gate sits immediately after it; every tier below can
half-execute a multi-step utterance, so all are gated. This is the least
surprising spot — it changes routing for exactly the compound case and nothing
else.

Positives (route to brain): "open spotify and play the next music",
"open brave and vs code side by side, brave left 50%, vs code right",
"open notepad and minimize everything", "play some music and dim the brightness"
— all detected. Negatives (stay on their reflex): "open spotify"/"open brave"/
"launch vs code" → apps; "play rock and roll"/"play guns and roses" → spotify;
"open command and conquer" → apps; "remember … and …"/"remind me to buy milk and
eggs" → memory/single; "close chrome"/"minimize all windows"/"dim brightness to
zero"/"next track" → their tiers; "find X in Downloads and play it" → media — all
NOT compound. Whole default suite green.

Test counts: default 321 → 359 (+36 `test_compound`, +2 acceptance guard tests);
deselected unchanged at 9. No deviations — implemented as specified; no commits.
