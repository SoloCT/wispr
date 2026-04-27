from pathlib import Path

import pytest

from wispr_clone.config import Config, DEFAULT_CONFIG, load_config, save_config


def test_load_config_creates_defaults_when_missing(tmp_path: Path):
    p = tmp_path / "config.toml"
    cfg = load_config(p)
    assert p.exists()
    assert cfg.hotkey == DEFAULT_CONFIG["hotkey"]
    assert cfg.max_recording_seconds == DEFAULT_CONFIG["max_recording_seconds"]


def test_save_then_load_round_trip(tmp_path: Path):
    p = tmp_path / "config.toml"
    cfg = Config(
        hotkey="right ctrl",
        max_recording_seconds=120,
        sample_rate=22050,
        mic_device="Realtek",
        clipboard_restore_delay_ms=200,
    )
    save_config(p, cfg)
    loaded = load_config(p)
    assert loaded == cfg


def test_load_config_merges_partial_file_with_defaults(tmp_path: Path):
    p = tmp_path / "config.toml"
    p.write_text('hotkey = "f12"\n', encoding="utf-8")
    cfg = load_config(p)
    assert cfg.hotkey == "f12"
    assert cfg.max_recording_seconds == DEFAULT_CONFIG["max_recording_seconds"]


def test_from_dict_clamps_max_recording_seconds_high():
    cfg = Config.from_dict({"max_recording_seconds": 99999})
    assert cfg.max_recording_seconds == 600


def test_from_dict_clamps_max_recording_seconds_low():
    cfg = Config.from_dict({"max_recording_seconds": 0})
    assert cfg.max_recording_seconds == 1


def test_from_dict_falls_back_on_invalid_sample_rate():
    cfg = Config.from_dict({"sample_rate": 12345})
    assert cfg.sample_rate == DEFAULT_CONFIG["sample_rate"]


def test_from_dict_normalizes_hotkey_case_and_whitespace():
    cfg = Config.from_dict({"hotkey": "  Ctrl+Shift+D  "})
    assert cfg.hotkey == "ctrl+shift+d"


def test_from_dict_falls_back_on_blank_hotkey():
    cfg = Config.from_dict({"hotkey": "   "})
    assert cfg.hotkey == DEFAULT_CONFIG["hotkey"]


def test_from_dict_clamps_clipboard_restore_delay():
    cfg = Config.from_dict({"clipboard_restore_delay_ms": -50})
    assert cfg.clipboard_restore_delay_ms == 0
    cfg2 = Config.from_dict({"clipboard_restore_delay_ms": 999999})
    assert cfg2.clipboard_restore_delay_ms == 5000


def test_from_dict_handles_non_numeric_max_recording():
    cfg = Config.from_dict({"max_recording_seconds": "not-a-number"})
    assert cfg.max_recording_seconds == DEFAULT_CONFIG["max_recording_seconds"]
