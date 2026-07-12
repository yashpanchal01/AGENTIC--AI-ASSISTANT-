"""Typed event bus (issue 12): pub/sub semantics + overlay/audit subscribers."""

from __future__ import annotations

from jarvis.audit import BusAuditor, MemoryAuditLog, attach_audit
from jarvis.brain.fake import FakeBrain
from jarvis.confirm import FixedConfirmer
from jarvis.core import handle_command
from jarvis.events import ConfirmRequested, EventBus, StateChanged, TokenTick
from jarvis.overlay.bus import BusOverlay, attach_overlay
from jarvis.overlay.fake import FakeOverlay
from jarvis.overlay.lifecycle import handle_command_with_overlay
from jarvis.overlay.states import OverlayState
from jarvis.tts.fake import FakeSpeaker


# -- bus semantics -----------------------------------------------------------


def test_publish_reaches_subscribers_in_subscription_order() -> None:
    bus = EventBus()
    seen: list[tuple[str, object]] = []
    bus.subscribe(lambda e: seen.append(("first", e)))
    bus.subscribe(lambda e: seen.append(("second", e)))

    event = TokenTick(text="hi")
    bus.publish(event)

    assert seen == [("first", event), ("second", event)]


def test_unsubscribe_stops_delivery_and_is_idempotent() -> None:
    bus = EventBus()
    seen: list[object] = []
    unsubscribe = bus.subscribe(seen.append)

    bus.publish(TokenTick(text="one"))
    unsubscribe()
    unsubscribe()  # second call must be a no-op
    bus.publish(TokenTick(text="two"))

    assert [e.text for e in seen] == ["one"]


def test_broken_subscriber_is_isolated() -> None:
    bus = EventBus()
    seen: list[object] = []

    def broken(_event: object) -> None:
        raise RuntimeError("subscriber blew up")

    bus.subscribe(broken)
    bus.subscribe(seen.append)

    bus.publish(TokenTick(text="still delivered"))  # must not raise

    assert [e.text for e in seen] == ["still delivered"]


def test_same_handler_twice_unsubscribes_individually() -> None:
    bus = EventBus()
    seen: list[object] = []
    unsub_a = bus.subscribe(seen.append)
    bus.subscribe(seen.append)

    bus.publish(TokenTick(text="x"))
    assert len(seen) == 2

    unsub_a()
    bus.publish(TokenTick(text="y"))
    assert len(seen) == 3  # only one subscription remains


def test_reentrant_publish_from_subscriber_does_not_deadlock() -> None:
    bus = EventBus()
    seen: list[str] = []

    def chaining(event: object) -> None:
        assert isinstance(event, TokenTick)
        seen.append(event.text)
        if event.text == "outer":
            bus.publish(TokenTick(text="inner"))

    bus.subscribe(chaining)
    bus.publish(TokenTick(text="outer"))

    assert seen == ["outer", "inner"]


# -- overlay through the bus (byte-for-byte with direct calls) ----------------


def _run_confirm_scenario(overlay, *, raise_in_extra_subscriber: bool = False):
    """One ask-first turn: propose → yes → execute (rule-based FakeBrain)."""
    return handle_command_with_overlay(
        "delete the old logs folder",
        brain=FakeBrain(),
        speaker=FakeSpeaker(),
        overlay=overlay,
        confirmer=FixedConfirmer(answer=True),
        heard_dwell_s=0,
        speaking_min_s=0,
    )


def test_overlay_sequence_identical_direct_vs_bus() -> None:
    direct = FakeOverlay()
    _run_confirm_scenario(direct)

    bus = EventBus()
    inner = FakeOverlay()
    attach_overlay(bus, inner)
    result = _run_confirm_scenario(BusOverlay(bus, inner))

    assert result.ok
    assert inner.events == direct.events
    assert inner.states == direct.states
    assert inner.confirm_previews == direct.confirm_previews
    assert inner.confirm_armed == direct.confirm_armed


def test_broken_second_subscriber_does_not_change_overlay_or_result() -> None:
    direct = FakeOverlay()
    _run_confirm_scenario(direct)

    bus = EventBus()

    def broken(_event: object) -> None:
        raise RuntimeError("boom")

    bus.subscribe(broken)  # subscribed first — still cannot starve the overlay
    inner = FakeOverlay()
    attach_overlay(bus, inner)
    result = _run_confirm_scenario(BusOverlay(bus, inner))

    assert result.ok
    assert inner.events == direct.events


def test_bus_overlay_confirm_channel_delegates_and_publishes() -> None:
    bus = EventBus()
    events: list[object] = []
    bus.subscribe(events.append)
    inner = FakeOverlay()
    attach_overlay(bus, inner)
    front = BusOverlay(bus, inner)

    front.set_state(OverlayState.CONFIRM, transcript="Delete temp folder")
    assert inner.state is OverlayState.CONFIRM
    assert inner.transcript == "Delete temp folder"

    front.arm_confirm()
    assert inner.confirm_armed is True
    confirms = [e for e in events if isinstance(e, ConfirmRequested)]
    assert confirms == [ConfirmRequested(proposed_action="Delete temp folder")]

    # Bidirectional click channel passes straight through to the real overlay.
    front.queue_confirm(True)
    assert front.take_confirm_decision() is True
    front.disarm_confirm()
    assert inner.confirm_armed is False

    front.close()
    assert inner.closed is True


def test_multiple_overlay_subscribers_see_the_same_states() -> None:
    bus = EventBus()
    first = FakeOverlay()
    second = FakeOverlay()
    attach_overlay(bus, first)
    attach_overlay(bus, second)

    front = BusOverlay(bus, first)
    front.set_state(OverlayState.WORKING, transcript="open notepad")
    front.set_state(OverlayState.REST)

    assert first.events == second.events
    assert first.states == [OverlayState.WORKING, OverlayState.REST]


# -- audit through the bus (same records as direct logging) -------------------


def _strip_ts(events: list[dict]) -> list[dict]:
    return [{k: v for k, v in e.items() if k != "ts"} for e in events]


def test_audit_records_identical_direct_vs_bus() -> None:
    direct = MemoryAuditLog()
    handle_command(
        "open notepad", brain=FakeBrain(), speaker=FakeSpeaker(), audit=direct
    )

    bus = EventBus()
    sink = MemoryAuditLog()
    attach_audit(bus, sink)
    handle_command(
        "open notepad",
        brain=FakeBrain(),
        speaker=FakeSpeaker(),
        audit=BusAuditor(bus),
    )

    assert _strip_ts(sink.events) == _strip_ts(direct.events)


def test_audit_subscriber_ignores_non_audit_events() -> None:
    bus = EventBus()
    sink = MemoryAuditLog()
    attach_audit(bus, sink)

    bus.publish(TokenTick(text="not an audit record"))
    bus.publish(StateChanged(state=OverlayState.WORKING))

    assert sink.events == []
