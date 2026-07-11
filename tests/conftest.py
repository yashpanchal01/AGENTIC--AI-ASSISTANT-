"""Pytest isolation for JARVIS home, settings, and audit log (issue 11).

Redirects ``JARVIS_HOME`` to a temp directory so unit tests never read the
developer's ``~/.jarvis/settings.json`` or append to the real audit log.
Also sets ``JARVIS_AUDIT=0`` as a belt-and-suspenders disable for any code
path that still constructs a default audit logger.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_jarvis_home(tmp_path_factory, monkeypatch):
    home = tmp_path_factory.mktemp("jarvis_home")
    monkeypatch.setenv("JARVIS_HOME", str(home))
    monkeypatch.setenv("JARVIS_AUDIT", "0")
    # Clear explicit settings override if a developer shell exported one.
    monkeypatch.delenv("JARVIS_SETTINGS", raising=False)
    yield home
