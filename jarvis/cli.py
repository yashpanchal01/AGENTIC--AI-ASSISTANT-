"""Terminal front door for JARVIS (core loop + wake/hotkey + Aurora overlay).

Usage:
  py -3.13 -m jarvis                  # interactive REPL (text)
  py -3.13 -m jarvis --once "open notepad"
  py -3.13 -m jarvis --fake --once "what's 2+2"
  py -3.13 -m jarvis --listen         # one-shot mic → silence → whisper → brain
  py -3.13 -m jarvis --daemon         # wake word + hotkey front door (continuous)
  py -3.13 -m jarvis --overlay --listen
  py -3.13 -m jarvis --overlay --daemon
  py -3.13 -m jarvis --shoot-overlay
  py -3.13 -m jarvis --demo-overlay
"""

from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path
from typing import Any

from jarvis.audio.capture import MicRecorder
from jarvis.audio.silence import SilenceConfig
from jarvis.brain.claude_code import ClaudeCodeBrain
from jarvis.brain.fake import FakeBrain
from jarvis.config import JarvisConfig
from jarvis.connectivity import SocketConnectivity
from jarvis.core import handle_command
from jarvis.stt.fake import FakeTranscriber
from jarvis.tts.fake import FakeSpeaker
from jarvis.tts.piper import PiperSpeaker
from jarvis.voice import listen_and_handle


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="jarvis",
        description=(
            "JARVIS — wake/hotkey or text → whisper → brain → Piper (+ Aurora overlay)"
        ),
    )
    p.add_argument(
        "--once",
        metavar="COMMAND",
        help="Run a single typed command and exit",
    )
    p.add_argument(
        "--listen",
        action="store_true",
        help="Record from mic until silence, transcribe, run one command, exit",
    )
    p.add_argument(
        "--daemon",
        "--front-door",
        action="store_true",
        dest="daemon",
        help="Continuous front door: local wake word + optional hotkey push-to-talk",
    )
    p.add_argument(
        "--fake",
        action="store_true",
        help="Use the in-process FakeBrain (no Claude CLI)",
    )
    p.add_argument(
        "--fake-stt",
        metavar="TEXT",
        default=None,
        help="Skip mic/whisper; inject this transcript (for tests / demos)",
    )
    p.add_argument(
        "--fake-wake",
        action="store_true",
        help="Use FakeWakeDetector (fires once per cycle via scripted frames)",
    )
    p.add_argument(
        "--max-cycles",
        type=int,
        default=None,
        help="With --daemon, exit after N armed command cycles (tests / demos)",
    )
    p.add_argument(
        "--hotkey",
        default=None,
        help="Push-to-talk hotkey (default: ctrl+shift+j or JARVIS_HOTKEY)",
    )
    p.add_argument(
        "--no-hotkey",
        action="store_true",
        help="Disable global hotkey (wake word only)",
    )
    p.add_argument(
        "--wake-threshold",
        type=float,
        default=None,
        help="openWakeWord detection threshold (default 0.5)",
    )
    p.add_argument(
        "--no-speak",
        action="store_true",
        help="Do not run Piper; print replies only",
    )
    p.add_argument(
        "--model",
        default=None,
        help="Claude model (default: sonnet, or JARVIS_MODEL)",
    )
    p.add_argument(
        "--cwd",
        type=Path,
        default=None,
        help="Working directory for the brain",
    )
    p.add_argument(
        "--overlay",
        action="store_true",
        help="Show the Aurora overlay during listen/once/daemon (requires PySide6)",
    )
    p.add_argument(
        "--no-overlay",
        action="store_true",
        help="Force-disable overlay even for --daemon",
    )
    p.add_argument(
        "--shoot-overlay",
        action="store_true",
        help="Render overlay states to PNGs and exit (screenshot harness)",
    )
    p.add_argument(
        "--demo-overlay",
        action="store_true",
        help="Cycle the live overlay through armed→heard→working→speaking",
    )
    p.add_argument(
        "--overlay-out",
        type=Path,
        default=Path("benches") / "overlay_shots" / "results",
        help="Output directory for --shoot-overlay",
    )
    p.add_argument(
        "--google-login",
        action="store_true",
        help="One-time Google OAuth (Gmail + Calendar read-only); then exit",
    )
    p.add_argument(
        "--fake-google",
        action="store_true",
        help="Use sample in-process Gmail/Calendar data (no OAuth)",
    )
    p.add_argument(
        "--no-google",
        action="store_true",
        help="Disable Gmail/Calendar integration for this run",
    )
    return p


def make_brain(config: JarvisConfig, *, fake: bool):
    if fake:
        return FakeBrain()
    return ClaudeCodeBrain(config=config)


def make_speaker(config: JarvisConfig, *, no_speak: bool):
    if no_speak or not config.speak:
        return FakeSpeaker()
    return PiperSpeaker(config=config, fallback_to_print=True)


def make_transcriber(config: JarvisConfig, *, fake_stt: str | None):
    if fake_stt is not None:
        return FakeTranscriber(text=fake_stt)
    from jarvis.stt.whisper import WhisperTranscriber

    return WhisperTranscriber(
        model_name=config.whisper_model,
        device=config.whisper_device,
        compute_type=config.whisper_compute,
        dictionary_path=config.dictionary_path,
    )


def make_recorder(config: JarvisConfig, *, fake_stt: str | None) -> MicRecorder:
    silence = SilenceConfig(
        silence_duration_s=config.silence_duration_s,
        max_record_s=config.max_record_s,
    )
    if fake_stt is not None:
        # Synthetic speech then silence so SilenceTracker completes without a mic.
        import numpy as np

        sr = silence.sample_rate
        speech = np.full(int(sr * 0.5), 0.2, dtype=np.float32)
        quiet = np.zeros(int(sr * (config.silence_duration_s + 0.2)), dtype=np.float32)
        return MicRecorder(config=silence, blocks=[speech, quiet])
    return MicRecorder(config=silence)


def make_wake_detector(config: JarvisConfig, *, fake_wake: bool):
    if fake_wake:
        from jarvis.wake.fake import FakeWakeDetector

        # Fire on first frame of each wait (reset between cycles clears count via
        # fire_after re-armed in session by using a detector that fires every
        # fire_after frames from a fresh counter — we use fire_after_frames=1
        # and reset() which does not re-arm; session uses frames that keep
        # coming. Prefer a detector that fires once per process burst:
        return FakeWakeDetector(fire_after_frames=1)
    from jarvis.wake.factory import create_wake_detector

    return create_wake_detector(
        access_key=config.picovoice_access_key,
        threshold=config.wake_threshold,
        sensitivity=config.wake_sensitivity,
    )


def make_google(*, fake_google: bool, no_google: bool):
    if no_google:
        return None
    from jarvis.google.workspace import build_google_workspace

    return build_google_workspace(force_fake=fake_google)


def make_connectivity(config: JarvisConfig):
    """Real socket check when enabled; None skips the pre-check (tests / offline demos)."""
    if not config.check_connectivity:
        return None
    return SocketConnectivity()


def run_once(
    command: str,
    *,
    brain,
    speaker,
    overlay=None,
    google=None,
    connectivity=None,
) -> int:
    if overlay is not None:
        from jarvis.overlay.lifecycle import handle_command_with_overlay

        result = handle_command_with_overlay(
            command,
            brain=brain,
            speaker=speaker,
            overlay=overlay,
            google=google,
            connectivity=connectivity,
        )
    else:
        result = handle_command(
            command,
            brain=brain,
            speaker=speaker,
            google=google,
            connectivity=connectivity,
        )
    _print_result(result)
    return 0 if result.ok else 1


def run_listen(
    *,
    brain,
    speaker,
    recorder,
    transcriber,
    announce: bool = True,
    overlay=None,
    google=None,
    connectivity=None,
    unload_stt_after: bool = False,
) -> int:
    if announce:
        print("Listening… (speak a command; ends on silence)")
    try:
        if overlay is not None:
            from jarvis.overlay.lifecycle import listen_and_handle_with_overlay

            outcome = listen_and_handle_with_overlay(
                recorder=recorder,
                transcriber=transcriber,
                brain=brain,
                speaker=speaker,
                overlay=overlay,
                google=google,
                connectivity=connectivity,
                unload_stt_after=unload_stt_after,
            )
        else:
            outcome = listen_and_handle(
                recorder=recorder,
                transcriber=transcriber,
                brain=brain,
                speaker=speaker,
                google=google,
                connectivity=connectivity,
                unload_stt_after=unload_stt_after,
            )
    except RuntimeError as e:
        print(f"JARVIS> voice error: {e}", file=sys.stderr)
        return 2

    if outcome.error:
        msg = {
            "no_speech": "I didn't hear anything.",
            "empty_transcript": "I heard sound but couldn't transcribe it.",
            "stt_failed": "I couldn't transcribe that.",
            "brain_unreachable": "My brain is unreachable right now.",
        }.get(outcome.error, outcome.error)
        print(f"JARVIS> {msg}")
        return 1

    print(f"You (voice)> {outcome.transcript}")
    assert outcome.command is not None
    _print_result(outcome.command)
    return 0 if outcome.command.ok else 1


def run_daemon(
    *,
    config: JarvisConfig,
    brain,
    speaker,
    transcriber,
    recorder,
    detector,
    overlay=None,
    google=None,
    connectivity=None,
    max_cycles: int | None = None,
    frames_factory=None,
    hotkey_controller=None,
    announce: bool = True,
) -> int:
    """Continuous wake + hotkey loop. Returns 0 after clean stop / max_cycles."""
    from jarvis.wake.session import FrontDoorSession

    if announce:
        hk = config.hotkey if config.enable_hotkey else "(disabled)"
        print(
            f"JARVIS front door  detector={getattr(detector, 'name', type(detector).__name__)}  "
            f"phrase={getattr(detector, 'phrase', '?')!r}  hotkey={hk}"
        )
        print("  Say the wake word or press the hotkey for each command. Ctrl+C to stop.")
        print()

    session = FrontDoorSession(
        detector=detector,
        recorder=recorder,
        transcriber=transcriber,
        brain=brain,
        speaker=speaker,
        overlay=overlay,
        google=google,
        hotkey=config.hotkey,
        enable_hotkey=config.enable_hotkey,
        frames_factory=frames_factory,
        hotkey_controller=hotkey_controller,
        connectivity=connectivity,
        unload_stt_after=config.unload_stt_between_commands,
    )

    def on_cycle(cycle) -> None:
        src = cycle.source
        out = cycle.outcome
        if out.error:
            msg = {
                "no_speech": "I didn't hear anything.",
                "empty_transcript": "I heard sound but couldn't transcribe it.",
            }.get(out.error, out.error)
            print(f"[{src}] JARVIS> {msg}")
            return
        print(f"[{src}] You (voice)> {out.transcript}")
        if out.command is not None:
            _print_result(out.command)

    session.on_cycle = on_cycle

    try:
        session.run(max_cycles=max_cycles)
    except KeyboardInterrupt:
        print()
        session.stop()
    finally:
        if hasattr(detector, "close"):
            try:
                detector.close()
            except Exception:
                pass

    if announce:
        print("front door stopped")
    return 0


def run_repl(
    *,
    brain,
    speaker,
    config: JarvisConfig,
    fake_stt: str | None,
    google=None,
    connectivity=None,
) -> int:
    print(
        "JARVIS  "
        "(type a command, :listen mic once, :n new session, :q quit)"
    )
    if isinstance(brain, ClaudeCodeBrain):
        print(f"  brain: Claude Code  model={brain.config.claude_model}")
    else:
        print("  brain: FakeBrain")
    print(f"  speaker: {type(speaker).__name__}")
    if google is not None:
        signed = getattr(google, "signed_in", True)
        print(f"  google: {'signed in' if signed else 'not signed in'} "
              f"({type(google).__name__})")
    else:
        print("  google: off")
    print()

    # Lazy STT — only load whisper when the user actually listens.
    transcriber = None

    while True:
        try:
            line = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not line:
            continue
        if line in (":q", ":quit", "quit", "exit"):
            break
        if line in (":n", ":new"):
            if hasattr(brain, "reset_session"):
                brain.reset_session()
            print("(new conversation)")
            continue
        if line in (":listen", ":v", ":voice"):
            if transcriber is None:
                print("(loading speech model…)")
                try:
                    transcriber = make_transcriber(config, fake_stt=fake_stt)
                except RuntimeError as e:
                    print(f"JARVIS> voice error: {e}")
                    continue
            recorder = make_recorder(config, fake_stt=fake_stt)
            run_listen(
                brain=brain,
                speaker=speaker,
                recorder=recorder,
                transcriber=transcriber,
                google=google,
                connectivity=connectivity,
                unload_stt_after=config.unload_stt_between_commands,
            )
            continue

        result = handle_command(
            line,
            brain=brain,
            speaker=speaker,
            google=google,
            connectivity=connectivity,
        )
        _print_result(result)

    print("bye")
    return 0


def _print_result(result) -> None:
    flags = []
    if result.denied:
        flags.append("denied")
    if not result.ok:
        flags.append("failed")
    flag_s = f"  [{', '.join(flags)}]" if flags else ""
    print(f"JARVIS> {result.reply}{flag_s}")
    if result.actions:
        names = " → ".join(
            f"{a.name}({a.detail})" if a.detail else a.name for a in result.actions
        )
        print(f"  actions: {names}")
    if result.session_id:
        sid = result.session_id
        shown = sid if len(sid) <= 12 else sid[:12] + "…"
        print(f"  session: {shown}")


def _run_with_qt_overlay(work, *, hold_after_s: float = 0.8) -> int:
    """Run *work(overlay)* on a worker thread while the Qt event loop paints."""
    try:
        from PySide6 import QtCore, QtWidgets
    except ImportError:
        print(
            'JARVIS> overlay needs PySide6. Install with: py -3.13 -m pip install -e ".[ui]"',
            file=sys.stderr,
        )
        return 2

    from jarvis.overlay.aurora import AuroraOverlay

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    overlay = AuroraOverlay()
    result_box: dict[str, int] = {"code": 1}

    class _Bridge(QtCore.QObject):
        finished = QtCore.Signal()

    bridge = _Bridge()

    def _quit_soon() -> None:
        # Runs on the UI thread (signal slot) — safe for QTimer.
        QtCore.QTimer.singleShot(int(hold_after_s * 1000), app.quit)

    bridge.finished.connect(_quit_soon)

    def runner() -> None:
        try:
            result_box["code"] = int(work(overlay))
        except Exception as exc:  # noqa: BLE001 — surface to console, quit UI
            print(f"JARVIS> overlay session error: {exc}", file=sys.stderr)
            result_box["code"] = 2
        finally:
            bridge.finished.emit()

    threading.Thread(target=runner, daemon=True).start()
    app.exec()
    overlay.close()
    return result_box["code"]


def _want_overlay(args) -> bool:
    if args.no_overlay:
        return False
    if args.overlay:
        return True
    # Default on for daemon when Qt is available (issue 05).
    if args.daemon:
        try:
            import PySide6  # noqa: F401
        except ImportError:
            return False
        return True
    return False


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = JarvisConfig.from_env()
    if args.model:
        config.claude_model = args.model
    if args.cwd:
        config.cwd = args.cwd
    if args.no_speak:
        config.speak = False
    if args.hotkey:
        config.hotkey = args.hotkey
    if args.no_hotkey:
        config.enable_hotkey = False
    if args.wake_threshold is not None:
        config.wake_threshold = args.wake_threshold

    if args.google_login:
        from jarvis.google.oauth import run_oauth_login

        try:
            path = run_oauth_login()
        except (FileNotFoundError, RuntimeError) as e:
            print(f"JARVIS> Google login failed: {e}", file=sys.stderr)
            return 2
        print(f"JARVIS> Google signed in (Gmail + Calendar read-only). Token: {path}")
        return 0

    if args.shoot_overlay:
        from jarvis.overlay.aurora import shoot_overlay_states

        paths = shoot_overlay_states(args.overlay_out)
        for path in paths:
            print(f"wrote {path}")
        return 0

    if args.demo_overlay:
        from jarvis.overlay.aurora import run_overlay_demo

        return run_overlay_demo()

    brain = make_brain(config, fake=args.fake)
    speaker = make_speaker(config, no_speak=args.no_speak)
    use_overlay = _want_overlay(args)
    # --fake enables sample Google data so demos work offline; real runs load
    # tokens via build_google_workspace when signed in. --no-google disables.
    use_fake_google = bool(args.fake_google or (args.fake and not args.no_google))
    google = make_google(fake_google=use_fake_google, no_google=args.no_google)
    # Fake brain needs no network; skip connectivity pre-check so offline demos work.
    connectivity = None if args.fake else make_connectivity(config)

    if args.daemon:
        if args.once is not None or args.listen:
            print(
                "Use --daemon alone (not with --once / --listen).",
                file=sys.stderr,
            )
            return 2
        try:
            # Fake STT for daemon demos still needs multi-session audio for each cycle.
            if args.fake_stt is not None:
                import numpy as np

                silence = SilenceConfig(
                    silence_duration_s=config.silence_duration_s,
                    max_record_s=config.max_record_s,
                )
                sr = silence.sample_rate
                speech = np.full(int(sr * 0.5), 0.2, dtype=np.float32)
                quiet = np.zeros(
                    int(sr * (config.silence_duration_s + 0.2)), dtype=np.float32
                )
                n = args.max_cycles or 1
                sessions = [[speech, quiet] for _ in range(max(n * 2, 2))]
                recorder = MicRecorder(config=silence, block_sessions=sessions)
                transcriber = FakeTranscriber(text=args.fake_stt)
            else:
                transcriber = make_transcriber(config, fake_stt=None)
                recorder = make_recorder(config, fake_stt=None)
            detector = make_wake_detector(config, fake_wake=args.fake_wake)
        except RuntimeError as e:
            print(f"JARVIS> front door error: {e}", file=sys.stderr)
            return 2

        frames_factory = None
        if args.fake_wake:
            import itertools

            import numpy as np

            fl = detector.frame_length

            def frames_factory() -> Any:
                # Endless silence frames; FakeWakeDetector fires via fire_after
                # (re-armed by detector.reset() at the start of each wait).
                return (np.zeros(fl, dtype=np.int16) for _ in itertools.count())

        def _daemon_work(overlay=None) -> int:
            return run_daemon(
                config=config,
                brain=brain,
                speaker=speaker,
                transcriber=transcriber,
                recorder=recorder,
                detector=detector,
                overlay=overlay,
                google=google,
                connectivity=connectivity,
                max_cycles=args.max_cycles,
                frames_factory=frames_factory,
                announce=True,
            )

        if use_overlay:
            # Daemon keeps running — hold_after only applies when work returns.
            return _run_with_qt_overlay(
                lambda ov: _daemon_work(ov),
                hold_after_s=0.3,
            )
        return _daemon_work(None)

    if args.listen or args.fake_stt is not None:
        if args.once is not None:
            print("Use either --once or --listen/--fake-stt, not both.", file=sys.stderr)
            return 2
        try:
            transcriber = make_transcriber(config, fake_stt=args.fake_stt)
            recorder = make_recorder(config, fake_stt=args.fake_stt)
        except RuntimeError as e:
            print(f"JARVIS> voice error: {e}", file=sys.stderr)
            return 2

        if use_overlay:
            return _run_with_qt_overlay(
                lambda ov: run_listen(
                    brain=brain,
                    speaker=speaker,
                    recorder=recorder,
                    transcriber=transcriber,
                    announce=args.fake_stt is None,
                    overlay=ov,
                    google=google,
                    connectivity=connectivity,
                    unload_stt_after=config.unload_stt_between_commands,
                )
            )
        return run_listen(
            brain=brain,
            speaker=speaker,
            recorder=recorder,
            transcriber=transcriber,
            announce=args.fake_stt is None,
            google=google,
            connectivity=connectivity,
            unload_stt_after=config.unload_stt_between_commands,
        )

    if args.once is not None:
        if use_overlay:
            return _run_with_qt_overlay(
                lambda ov: run_once(
                    args.once,
                    brain=brain,
                    speaker=speaker,
                    overlay=ov,
                    google=google,
                    connectivity=connectivity,
                )
            )
        return run_once(
            args.once,
            brain=brain,
            speaker=speaker,
            google=google,
            connectivity=connectivity,
        )

    if args.overlay and not args.daemon:
        print(
            "--overlay applies to --listen / --once / --fake-stt / --daemon "
            "(or use --demo-overlay / --shoot-overlay).",
            file=sys.stderr,
        )
        return 2

    return run_repl(
        brain=brain,
        speaker=speaker,
        config=config,
        fake_stt=None,
        google=google,
        connectivity=connectivity,
    )


if __name__ == "__main__":
    sys.exit(main())
