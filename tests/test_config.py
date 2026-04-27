from pathlib import Path

import pytest

from wispr_clone.config import Config, DEFAULT_CONFIG, load_config, save_config


def test_load_config_creates_defaults_when_missing(tmp_path: Path):
    p = tmp_path / "config.toml"
    cfg = load_config(p)
    assert p.exists()
    assert cfg.hotkey_english == DEFAULT_CONFIG["hotkey_english"]
    assert cfg.hotkey_cantonese == DEFAULT_CONFIG["hotkey_cantonese"]
    assert cfg.max_recording_seconds == DEFAULT_CONFIG["max_recording_seconds"]
    assert cfg.enable_smart_cleanup is False


def test_save_then_load_round_trip(tmp_path: Path):
    p = tmp_path / "config.toml"
    cfg = Config(
        hotkey_english="right ctrl",
        hotkey_cantonese="ctrl+alt+windows",
        max_recording_seconds=120,
        sample_rate=22050,
        mic_device="Realtek",
        clipboard_restore_delay_ms=200,
        enable_smart_cleanup=True,
        cleanup_model="llama-3.1-8b-instant",
        cleanup_timeout_ms=2500,
    )
    save_config(p, cfg)
    loaded = load_config(p)
    assert loaded == cfg


def test_load_config_merges_partial_file_with_defaults(tmp_path: Path):
    p = tmp_path / "config.toml"
    p.write_text('hotkey_english = "f12"\n', encoding="utf-8")
    cfg = load_config(p)
    assert cfg.hotkey_english == "f12"
    assert cfg.hotkey_cantonese == DEFAULT_CONFIG["hotkey_cantonese"]
    assert cfg.max_recording_seconds == DEFAULT_CONFIG["max_recording_seconds"]


def test_legacy_hotkey_field_migrates_to_english(tmp_path: Path):
    p = tmp_path / "config.toml"
    p.write_text('hotkey = "ctrl+windows"\n', encoding="utf-8")
    cfg = load_config(p)
    assert cfg.hotkey_english == "ctrl+windows"
    assert cfg.hotkey_cantonese == DEFAULT_CONFIG["hotkey_cantonese"]


def test_legacy_hotkey_field_loses_to_explicit_english():
    cfg = Config.from_dict({"hotkey": "f5", "hotkey_english": "f9"})
    assert cfg.hotkey_english == "f9"


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
    cfg = Config.from_dict({"hotkey_english": "  Ctrl+Shift+D  "})
    assert cfg.hotkey_english == "ctrl+shift+d"


def test_from_dict_normalizes_cantonese_hotkey():
    cfg = Config.from_dict({"hotkey_cantonese": "  CTRL+Alt+Windows  "})
    assert cfg.hotkey_cantonese == "ctrl+alt+windows"


def test_from_dict_falls_back_on_blank_hotkey():
    cfg = Config.from_dict({"hotkey_english": "   "})
    assert cfg.hotkey_english == DEFAULT_CONFIG["hotkey_english"]


def test_from_dict_clamps_clipboard_restore_delay():
    cfg = Config.from_dict({"clipboard_restore_delay_ms": -50})
    assert cfg.clipboard_restore_delay_ms == 0
    cfg2 = Config.from_dict({"clipboard_restore_delay_ms": 999999})
    assert cfg2.clipboard_restore_delay_ms == 5000


def test_from_dict_handles_non_numeric_max_recording():
    cfg = Config.from_dict({"max_recording_seconds": "not-a-number"})
    assert cfg.max_recording_seconds == DEFAULT_CONFIG["max_recording_seconds"]


def test_smart_cleanup_default_off():
    cfg = Config.from_dict({})
    assert cfg.enable_smart_cleanup is False


def test_smart_cleanup_accepts_truthy_strings():
    cfg = Config.from_dict({"enable_smart_cleanup": "true"})
    assert cfg.enable_smart_cleanup is True
    cfg2 = Config.from_dict({"enable_smart_cleanup": "off"})
    assert cfg2.enable_smart_cleanup is False


def test_cleanup_timeout_clamped():
    cfg = Config.from_dict({"cleanup_timeout_ms": 1})
    assert cfg.cleanup_timeout_ms == 100
    cfg2 = Config.from_dict({"cleanup_timeout_ms": 99999})
    assert cfg2.cleanup_timeout_ms == 30000
