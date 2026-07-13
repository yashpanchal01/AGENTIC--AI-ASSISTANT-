"""SPINE overlay (issue 18): event -> surface mapping + a Qt smoke.

The unit + integration tests drive the headless :class:`SpineSurface` with no
GUI/display. A separate subprocess smoke launches the real Qt widget with a
self-quit hook (``JARVIS_SPINE_SMOKE``) under the offscreen platform and
asserts it animates a fake trace with zero Qt errors, then exits 0.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from jarvis.events import (
    BrainSelected,
    ConfirmRequested,
    Fault,
    ListeningChanged,
    StateChanged,
    StepFailed,
    StepFinished,
    StepStarted,
    TaskCompleted,
    TokenTick,
)
from jarvis.overlay.spine_surface import (
    SpineSubscriber,
    SpineSurface,
    SpineVisual,
)
from jarvis.overlay.states import OverlayState


# -- unit: event -> surface mapping (headless) --------------------------------


def test_step_events_build_the_ledger() -> None:
    s = SpineSurface()
    s.apply_state(OverlayState.WORKING)
    s.handle_event(StepStarted(name="Bash", detail="notepad.exe", step_id="t1"))

    snap = s.snapshot()
    assert len(snap.steps) == 1
    assert snap.steps[0].name == "Bash"
    assert snap.steps[0].status == "active"

    s.handle_event(StepFinished(name="Bash", detail="notepad.exe", step_id="t1"))
    snap = s.snapshot()
    assert snap.steps[0].status == "done"
    assert len(snap.steps) == 1  # same step resolved, not duplicated


def test_ticker_advances_on_token_ticks() -> None:
    s = SpineSurface()
    assert s.snapshot().token_ticks == 0
    s.handle_event(TokenTick(text="Let me "))
    s.handle_event(TokenTick(text="open that."))
    snap = s.snapshot()
    assert snap.token_ticks == 2
    assert snap.token_chars == len("Let me ") + len("open that.")
    assert snap.last_token_text == "open that."


def test_brain_selected_sets_readout() -> None:
    s = SpineSurface()
    s.handle_event(BrainSelected(provider="claude"))
    assert s.snapshot().brain == "CLAUDE"
    s.handle_event(BrainSelected(provider="grok"))
    assert s.snapshot().brain == "GROK"


def test_step_failed_latches_fault_and_visual() -> None:
    s = SpineSurface()
    s.apply_state(OverlayState.WORKING)
    s.handle_event(StepStarted(name="Write", detail="C:/locked.txt", step_id="w1"))
    s.handle_event(
        StepFailed(name="Write", detail="C:/locked.txt", step_id="w1", error="locked")
    )
    snap = s.snapshot()
    assert snap.steps[0].status == "failed"
    assert snap.fault_latched is True
    assert "locked" in snap.fault_text
    assert snap.visual is SpineVisual.FAULT
    assert snap.fault_events == 1


def test_fault_event_latches_fault() -> None:
    s = SpineSurface()
    s.apply_state(OverlayState.WORKING)
    s.handle_event(Fault(error="brain unreachable", detail="timeout"))
    snap = s.snapshot()
    assert snap.fault_latched is True
    assert snap.visual is SpineVisual.FAULT
    assert "unreachable" in snap.fault_text


def test_confirm_requested_shows_ring_until_resolved() -> None:
    s = SpineSurface()
    s.apply_state(OverlayState.WORKING)
    s.handle_event(ConfirmRequested(proposed_action="delete the logs folder"))
    snap = s.snapshot()
    assert snap.commit_ring is True
    assert "logs" in snap.commit_prompt

    # Leaving CONFIRM (the flow resolving) clears the ring.
    s.apply_state(OverlayState.SPEAKING)
    assert s.snapshot().commit_ring is False


def test_confirm_state_also_raises_ring() -> None:
    s = SpineSurface()
    s.apply_state(OverlayState.CONFIRM, transcript="delete temp")
    assert s.snapshot().commit_ring is True


def test_task_completed_ok_fires_green_pulse() -> None:
    s = SpineSurface()
    assert s.snapshot().success_pulses == 0
    s.handle_event(TaskCompleted(reply="Done.", ok=True))
    assert s.snapshot().success_pulses == 1
    # Failure does not fire the green pulse.
    s.handle_event(TaskCompleted(reply="", ok=False, error="boom"))
    assert s.snapshot().success_pulses == 1


def test_task_completed_resolves_pending_ring() -> None:
    s = SpineSurface()
    s.handle_event(ConfirmRequested(proposed_action="x"))
    assert s.snapshot().commit_ring is True
    s.handle_event(TaskCompleted(reply="ok", ok=True))
    assert s.snapshot().commit_ring is False


def test_new_turn_clears_previous_ledger_and_fault() -> None:
    s = SpineSurface()
    s.apply_state(OverlayState.WORKING)
    s.handle_event(StepStarted(name="Bash", detail="x", step_id="a"))
    s.handle_event(StepFailed(name="Bash", detail="x", step_id="a", error="nope"))
    assert s.snapshot().fault_latched is True

    # Next command: HEARD begins a fresh turn.
    s.apply_state(OverlayState.HEARD, transcript="next command")
    snap = s.snapshot()
    assert snap.steps == ()
    assert snap.fault_latched is False
    assert snap.token_ticks == 0


def test_listening_changed_drives_mic_shutter_state() -> None:
    s = SpineSurface()
    assert s.snapshot().mic_muted is False  # listening by default

    # Not listening (resident paused) -> privacy-shutter should close.
    s.handle_event(ListeningChanged(listening=False))
    assert s.snapshot().mic_muted is True

    # Listening again (resumed) -> shutter opens.
    s.handle_event(ListeningChanged(listening=True))
    assert s.snapshot().mic_muted is False


def test_mic_mute_is_independent_of_a_new_turn() -> None:
    # Mute is a front-door state, not a per-command latch: a new turn must not
    # clear it (and in practice HEARD cannot fire while deaf).
    s = SpineSurface()
    s.handle_event(ListeningChanged(listening=False))
    s.apply_state(OverlayState.HEARD, transcript="ignored while deaf")
    assert s.snapshot().mic_muted is True


def test_resident_pause_publishes_listening_changed_to_surface() -> None:
    """The exact cli wiring: resident.on_state_change -> bus -> SPINE surface."""
    from jarvis.events import EventBus
    from jarvis.resident import ResidentController

    bus = EventBus()
    s = SpineSurface()
    bus.subscribe(SpineSubscriber(s))

    resident = ResidentController()
    resident.on_state_change = lambda state: bus.publish(
        ListeningChanged(listening=(state == "running"))
    )

    resident.pause()
    assert s.snapshot().mic_muted is True  # shutter closed while paused
    resident.resume()
    assert s.snapshot().mic_muted is False  # shutter open while running


def test_rest_hides_plate() -> None:
    s = SpineSurface()
    s.apply_state(OverlayState.WORKING)
    assert s.snapshot().active is True
    s.apply_state(OverlayState.REST)
    assert s.snapshot().active is False
    assert s.snapshot().visual is None


# -- robustness: malformed / out-of-order events ------------------------------


class _Weird:
    """An event object of an unknown type with missing/odd attributes."""

    name = None


def test_malformed_and_out_of_order_events_do_not_raise() -> None:
    s = SpineSurface()
    # Finish before start — tolerated.
    s.handle_event(StepFinished(name="Ghost", detail="", step_id="z"))
    assert s.snapshot().steps[0].status == "done"

    # Unknown event type — ignored, no crash.
    s.handle_event(_Weird())
    s.handle_event(None)
    s.handle_event(object())

    # Odd payloads.
    s.handle_event(BrainSelected(provider=""))
    s.handle_event(TokenTick(text=""))
    s.handle_event(StepStarted(name="", detail="", step_id=None))
    # None of these raise; surface still snapshots cleanly.
    assert isinstance(s.snapshot().revision, int)


def test_subscriber_ignores_state_changed() -> None:
    s = SpineSurface()
    sub = SpineSubscriber(s)
    # StateChanged goes through the set_state/apply_state path, not the rich one.
    sub(StateChanged(state=OverlayState.WORKING, transcript="hi"))
    # No visual mutation from the subscriber for StateChanged.
    assert s.snapshot().state is OverlayState.REST
    # But rich events flow through.
    sub(TokenTick(text="hey"))
    assert s.snapshot().token_ticks == 1


# -- integration: a scripted brain session trace ------------------------------


def test_scripted_session_trace_drives_all_surfaces() -> None:
    """Replay a full multi-step session and assert each surface transition."""
    s = SpineSurface()
    sub = SpineSubscriber(s)

    # Wake + hear a command.
    s.apply_state(OverlayState.ARMED, level=0.6)
    s.apply_state(OverlayState.HEARD, transcript="play focus mix and log gpu temps")
    sub(BrainSelected(provider="claude"))
    s.apply_state(OverlayState.WORKING, transcript="play focus mix and log gpu temps")

    # First step runs to completion, tokens stream.
    sub(StepStarted(name="spotify", detail="queue focus mix", step_id="s1"))
    sub(TokenTick(text="queuing your focus mix "))
    sub(StepFinished(name="spotify", detail="queue focus mix", step_id="s1"))
    snap = s.snapshot()
    assert [st.status for st in snap.steps] == ["done"]
    assert snap.brain == "CLAUDE"
    assert snap.token_ticks == 1

    # Second step needs confirmation -> commit ring, then resolves.
    sub(StepStarted(name="Bash", detail="nvidia-smi", step_id="s2"))
    sub(ConfirmRequested(proposed_action="append gpu-log.md"))
    s.apply_state(OverlayState.CONFIRM, transcript="append gpu-log.md")
    assert s.snapshot().commit_ring is True
    s.apply_state(OverlayState.WORKING)
    sub(StepFinished(name="Bash", detail="nvidia-smi", step_id="s2"))
    assert s.snapshot().commit_ring is False
    assert [st.status for st in s.snapshot().steps] == ["done", "done"]

    # Speak the reply and complete the task -> green pulse.
    s.apply_state(OverlayState.SPEAKING, transcript="done")
    sub(TaskCompleted(reply="Focus mix playing. GPU logged.", ok=True))
    final = s.snapshot()
    assert final.success_pulses == 1
    assert final.fault_latched is False

    # Back to rest hides the plate.
    s.apply_state(OverlayState.REST)
    assert s.snapshot().active is False


def test_fault_trace_shows_fault_then_clears_next_turn() -> None:
    s = SpineSurface()
    sub = SpineSubscriber(s)
    s.apply_state(OverlayState.WORKING, transcript="open the vault")
    sub(StepStarted(name="Bash", detail="mount", step_id="f1"))
    sub(StepFailed(name="Bash", detail="mount", step_id="f1", error="timeout"))
    mid = s.snapshot()
    assert mid.visual is SpineVisual.FAULT
    assert mid.fault_latched is True
    assert mid.steps[0].status == "failed"

    # Next command clears the fault latch.
    s.apply_state(OverlayState.HEARD, transcript="try again")
    assert s.snapshot().fault_latched is False


# -- Qt-level: constructs + paints without touching Qt off-thread -------------


def test_spine_widget_paints_from_surface() -> None:
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets

    from jarvis.overlay.spine import SpineOverlay

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w = SpineOverlay()
    try:
        w.set_state(OverlayState.WORKING, transcript="open notepad")
        w._apply_event(StepStarted(name="Bash", detail="notepad", step_id="t1"))
        w._apply_event(BrainSelected(provider="claude"))
        w._apply_event(TokenTick(text="working "))
        app.processEvents()
        # Force a paint pass headlessly (no show()).
        w._reveal = 1.0
        pm = w.grab()
        assert pm.width() > 0 and pm.height() > 0
        snap = w._snap
        assert snap.brain == "CLAUDE"
        assert snap.steps[0].name == "Bash"
    finally:
        w.close()


def test_spine_widget_shutter_closes_and_reveals_when_muted() -> None:
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets

    from jarvis.overlay.spine import SpineOverlay

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w = SpineOverlay()
    try:
        # Idle + listening: shutter open, plate wants to be hidden.
        for _ in range(10):
            w._tick()
        assert w.shutter < 0.1
        assert w._reveal_to == 0.0

        # Not listening (resident paused): shutter drives closed and the plate
        # reveals so the closed privacy-shutter is actually visible.
        w._apply_event(ListeningChanged(listening=False))
        for _ in range(30):
            w._tick()
        assert w.shutter > 0.8
        assert w._reveal_to == 1.0

        # Resume: shutter reopens.
        w._apply_event(ListeningChanged(listening=True))
        for _ in range(30):
            w._tick()
        assert w.shutter < 0.2
    finally:
        w.close()


def test_spine_gui_smoke_subprocess() -> None:
    """Launch the real widget with the self-quit hook; assert clean exit 0."""
    pytest.importorskip("PySide6")

    env = dict(os.environ)
    env["JARVIS_SPINE_SMOKE"] = "1"
    env["QT_QPA_PLATFORM"] = "offscreen"  # no popping window; still exercises paint
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "from jarvis.overlay.spine import run_spine_smoke; "
            "import sys; sys.exit(run_spine_smoke())",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "SMOKE OK" in proc.stdout
    # Zero Qt paint errors/warnings.
    lowered = proc.stderr.lower()
    assert "qpainter" not in lowered, proc.stderr
    assert "qwidget::repaint" not in lowered, proc.stderr
