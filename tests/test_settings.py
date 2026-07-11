"""User settings file load + merge into JarvisConfig (issue 11)."""

from __future__ import annotations

import json
from pathlib import Path

from jarvis.config import JarvisConfig
from jarvis.settings import (
    apply_user_settings,
    load_settings,
    parse_settings_dict,
)


def test_load_settings_missing_file(tmp_path: Path) -> None:
    s = load_settings(tmp_path / "nope.json")
    assert s.hotkey is None
    assert s.approved_folders is None
    assert s.voice is None


def test_load_settings_json(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "hotkey": "ctrl+alt+j",
                "approved_folders": [str(tmp_path / "docs"), str(tmp_path / "dl")],
                "voice": str(tmp_path / "voice.onnx"),
                "enable_hotkey": False,
            }
        ),
        encoding="utf-8",
    )
    s = load_settings(path)
    assert s.hotkey == "ctrl+alt+j"
    assert s.enable_hotkey is False
    assert s.approved_folders == (tmp_path / "docs", tmp_path / "dl")
    assert s.voice == tmp_path / "voice.onnx"


def test_voice_alias_piper_model() -> None:
    s = parse_settings_dict({"piper_model": r"C:\voices\me.onnx"})
    assert s.voice == Path(r"C:\voices\me.onnx")


def test_apply_user_settings_overrides_config(tmp_path: Path) -> None:
    cfg = JarvisConfig(
        hotkey="ctrl+shift+j",
        enable_hotkey=True,
        approved_folders=(tmp_path / "old",),
        piper_model=None,
    )
    settings = parse_settings_dict(
        {
            "hotkey": "f9",
            "approved_folders": [str(tmp_path / "new")],
            "voice": str(tmp_path / "v.onnx"),
        }
    )
    out = apply_user_settings(cfg, settings)
    assert out.hotkey == "f9"
    assert out.approved_folders == (tmp_path / "new",)
    assert out.piper_model == tmp_path / "v.onnx"
    # Unrelated fields preserved
    assert out.enable_hotkey is True


def test_apply_empty_settings_is_noop() -> None:
    cfg = JarvisConfig(hotkey="ctrl+shift+j")
    out = apply_user_settings(cfg, parse_settings_dict({}))
    assert out.hotkey == "ctrl+shift+j"


def test_from_env_applies_settings_file(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"hotkey": "ctrl+shift+k"}), encoding="utf-8")
    monkeypatch.setenv("JARVIS_SETTINGS", str(path))
    # Clear conflicting env
    monkeypatch.delenv("JARVIS_HOTKEY", raising=False)
    cfg = JarvisConfig.from_env(apply_settings=True)
    assert cfg.hotkey == "ctrl+shift+k"


def test_from_env_can_skip_settings(monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_HOTKEY", "ctrl+shift+z")
    cfg = JarvisConfig.from_env(apply_settings=False)
    assert cfg.hotkey == "ctrl+shift+z"


def test_invalid_json_yields_empty(tmp_path: Path, capsys) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{not json", encoding="utf-8")
    s = load_settings(path)
    assert s.hotkey is None
    err = capsys.readouterr().err
    assert "invalid JSON" in err
    assert str(path) in err
