"""Pause / resume gate and autostart registration (issue 11)."""

from __future__ import annotations

import threading
import time

import numpy as np

from jarvis.audio.capture import MicRecorder
from jarvis.audio.silence import SilenceConfig
from jarvis.audit import MemoryAuditLog
from jarvis.autostart import (
    MemoryRegistry,
    default_daemon_command,
    install_autostart,
    is_autostart_installed,
    uninstall_autostart,
)
from jarvis.brain.fake import FakeBrain
from jarvis.resident import ResidentController
from jarvis.stt.fake import FakeTranscriber
from jarvis.tts.fake import FakeSpeaker
from jarvis.types import BrainTurn
from jarvis.wake.fake import FakeWakeDetector
from jarvis.wake.hotkey import FakeHotkeyController
from jarvis.wake.session import FrontDoorSession


def _speech_quiet(sr: int = 16_000) -> list[np.ndarray]:
    speech = np.full(int(sr * 0.5), 0.2, dtype=np.float32)
    quiet = np.zeros(int(sr * 1.0), dtype=np.float32)
    return [speech, quiet]


def _silence_cfg() -> SilenceConfig:
    return SilenceConfig(silence_duration_s=0.5, min_speech_s=0.2)


def test_resident_pause_resume_quit_states() -> None:
    audit = MemoryAuditLog()
    r = ResidentController(audit=audit)
    assert r.state == "running"
    assert not r.is_paused
    r.pause()
    assert r.is_paused
    assert r.state == "paused"
    r.resume()
    assert not r.is_paused
    assert r.state == "running"
    r.quit()
    assert r.is_stopping
    assert r.state == "stopping"
    events = [e["event"] for e in audit.events]
    assert events == ["pause", "resume", "quit"]


def test_pause_makes_front_door_deaf() -> None:
    """While paused, wake triggers must not run the armed pipeline."""
    brain = FakeBrain(
        script=[
            BrainTurn(reply="First.", actions=()),
            BrainTurn(reply="Second.", actions=()),
        ]
    )
    speaker = FakeSpeaker()
    stt = FakeTranscriber(text=["open a", "open b"])
    rec = MicRecorder(
        config=_silence_cfg(),
        block_sessions=[_speech_quiet(), _speech_quiet()],
    )
    fl = 512
    detector = FakeWakeDetector(fire_after_frames=1)
    audit = MemoryAuditLog()
    resident = ResidentController(audit=audit)

    def frames():
        return (np.zeros(fl, dtype=np.int16) for _ in range(8))

    session = FrontDoorSession(
        detector=detector,
        recorder=rec,
        transcriber=stt,
        brain=brain,
        speaker=speaker,
        enable_hotkey=False,
        frames_factory=frames,
        resident=resident,
        audit=audit,
        heard_dwell_s=0,
        speaking_min_s=0,
    )

    # Start paused — should produce zero cycles until resume.
    resident.pause()

    def _run() -> None:
        session.run(max_cycles=1)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    time.sleep(0.15)
    assert session.cycles == []
    assert speaker.spoken == []

    resident.resume()
    t.join(timeout=5.0)
    assert not t.is_alive()
    assert len(session.cycles) == 1
    assert speaker.spoken == ["First."]
    assert any(e["event"] == "front_door_armed" for e in audit.events)


def test_quit_stops_session() -> None:
    brain = FakeBrain(script=[BrainTurn(reply="Nope.", actions=())])
    speaker = FakeSpeaker()
    stt = FakeTranscriber(text="hello")
    rec = MicRecorder(config=_silence_cfg(), blocks=_speech_quiet())
    # Never fire wake — wait until quit.
    detector = FakeWakeDetector(detections=[None] * 10_000)
    resident = ResidentController()

    def silent_frames():
        def gen():
            while not resident.is_stopping:
                yield np.zeros(0, dtype=np.int16)
                time.sleep(0.01)
            yield np.zeros(0, dtype=np.int16)

        return gen()

    session = FrontDoorSession(
        detector=detector,
        recorder=rec,
        transcriber=stt,
        brain=brain,
        speaker=speaker,
        enable_hotkey=False,
        frames_factory=silent_frames,
        resident=resident,
    )

    t = threading.Thread(target=lambda: session.run(max_cycles=5), daemon=True)
    t.start()
    time.sleep(0.1)
    resident.quit()
    t.join(timeout=5.0)
    assert not t.is_alive()
    assert session.cycles == []


def test_autostart_install_uninstall_with_memory_registry() -> None:
    reg = MemoryRegistry()
    assert not is_autostart_installed(backend=reg)
    cmd = install_autostart(backend=reg, command="py -3.13 -m jarvis --daemon")
    assert cmd == "py -3.13 -m jarvis --daemon"
    assert is_autostart_installed(backend=reg)
    assert reg.get_value("JARVIS") == cmd
    assert uninstall_autostart(backend=reg) is True
    assert not is_autostart_installed(backend=reg)
    assert uninstall_autostart(backend=reg) is False


def test_default_daemon_command_uses_executable() -> None:
    # prefer_pythonw=False so the test does not depend on a local pythonw.exe.
    cmd = default_daemon_command(
        python_exe=r"C:\Python\python.exe", prefer_pythonw=False
    )
    assert cmd == r"C:\Python\python.exe -m jarvis --daemon"
    cmd2 = default_daemon_command(
        python_exe=r"C:\Program Files\Python\python.exe", prefer_pythonw=False
    )
    assert cmd2.startswith('"')
    assert "-m jarvis --daemon" in cmd2


def test_hotkey_deaf_while_paused() -> None:
    """Hotkey presses while paused must not run a cycle (issue 11 / review #8)."""
    brain = FakeBrain(
        script=[
            BrainTurn(reply="After resume.", actions=()),
        ]
    )
    speaker = FakeSpeaker()
    stt = FakeTranscriber(text="open chrome")
    rec = MicRecorder(config=_silence_cfg(), blocks=_speech_quiet())
    detector = FakeWakeDetector(detections=[None] * 10_000)
    audit = MemoryAuditLog()
    resident = ResidentController(audit=audit)
    hk = FakeHotkeyController()

    def silent_frames():
        def gen():
            while not resident.is_stopping:
                yield np.zeros(0, dtype=np.int16)
                time.sleep(0.01)
            yield np.zeros(0, dtype=np.int16)

        return gen()

    session = FrontDoorSession(
        detector=detector,
        recorder=rec,
        transcriber=stt,
        brain=brain,
        speaker=speaker,
        enable_hotkey=True,
        hotkey_controller=hk,
        frames_factory=silent_frames,
        resident=resident,
        audit=audit,
        heard_dwell_s=0,
        speaking_min_s=0,
    )

    resident.pause()

    def _run() -> None:
        session.run(max_cycles=1)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    time.sleep(0.12)
    # Fire hotkey while paused — must be ignored.
    hk.fire()
    time.sleep(0.15)
    assert session.cycles == []
    assert speaker.spoken == []

    resident.resume()
    # Now fire hotkey so the one allowed cycle can complete.
    time.sleep(0.05)
    hk.fire()
    t.join(timeout=5.0)
    assert not t.is_alive()
    assert len(session.cycles) == 1
    assert session.cycles[0].source == "hotkey"
    assert speaker.spoken == ["After resume."]


def test_pause_aborts_in_flight_wait_for_trigger() -> None:
    """Pause while waiting must leave wait_for_trigger (hard deaf, review #3)."""
    brain = FakeBrain(script=[BrainTurn(reply="Nope.", actions=())])
    speaker = FakeSpeaker()
    stt = FakeTranscriber(text="hello")
    rec = MicRecorder(config=_silence_cfg(), blocks=_speech_quiet())
    detector = FakeWakeDetector(detections=[None] * 10_000)
    resident = ResidentController()

    entered = threading.Event()
    left_wait = threading.Event()

    def silent_frames():
        def gen():
            entered.set()
            while not resident.is_paused and not resident.is_stopping:
                yield np.zeros(0, dtype=np.int16)
                time.sleep(0.01)
            left_wait.set()
            # Keep yielding until stop so the outer loop can re-enter pause wait.
            while not resident.is_stopping:
                yield np.zeros(0, dtype=np.int16)
                time.sleep(0.02)
            yield np.zeros(0, dtype=np.int16)

        return gen()

    session = FrontDoorSession(
        detector=detector,
        recorder=rec,
        transcriber=stt,
        brain=brain,
        speaker=speaker,
        enable_hotkey=False,
        frames_factory=silent_frames,
        resident=resident,
    )

    t = threading.Thread(target=lambda: session.run(max_cycles=1), daemon=True)
    t.start()
    assert entered.wait(timeout=2.0)
    time.sleep(0.05)
    resident.pause()
    assert left_wait.wait(timeout=2.0)
    time.sleep(0.1)
    assert session.cycles == []
    assert speaker.spoken == []
    resident.quit()
    t.join(timeout=5.0)
    assert not t.is_alive()
