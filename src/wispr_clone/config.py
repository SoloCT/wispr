"""Config loading + persistence for wispr-clone."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import tomli_w
from dotenv import load_dotenv


DEFAULT_CONFIG = {
    "hotkey": "f9",
    "max_recording_seconds": 90,
    "sample_rate": 16000,
    "mic_device": "",
    "clipboard_restore_delay_ms": 150,
}

MAX_RECORDING_SECONDS_LIMIT = 600  # 10 min hard cap; longer hits Groq file-size limits
VALID_SAMPLE_RATES = (8000, 16000, 22050, 24000, 32000, 44100, 48000)


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass
class Config:
    hotkey: str
    max_recording_seconds: int
    sample_rate: int
    mic_device: str
    clipboard_restore_delay_ms: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        merged = {**DEFAULT_CONFIG, **data}

        hotkey = str(merged["hotkey"]).strip().lower() or DEFAULT_CONFIG["hotkey"]

        max_rec = _coerce_int(merged["max_recording_seconds"], DEFAULT_CONFIG["max_recording_seconds"])
        max_rec = max(1, min(MAX_RECORDING_SECONDS_LIMIT, max_rec))

        sample_rate = _coerce_int(merged["sample_rate"], DEFAULT_CONFIG["sample_rate"])
        if sample_rate not in VALID_SAMPLE_RATES:
            sample_rate = DEFAULT_CONFIG["sample_rate"]

        restore_ms = _coerce_int(merged["clipboard_restore_delay_ms"], DEFAULT_CONFIG["clipboard_restore_delay_ms"])
        restore_ms = max(0, min(5000, restore_ms))

        return cls(
            hotkey=hotkey,
            max_recording_seconds=max_rec,
            sample_rate=sample_rate,
            mic_device=str(merged["mic_device"]),
            clipboard_restore_delay_ms=restore_ms,
        )


def load_config(path: Path) -> Config:
    """Load config.toml. Writes defaults if the file is missing."""
    if not path.exists():
        path.write_text(_format_toml(DEFAULT_CONFIG), encoding="utf-8")
        return Config.from_dict(DEFAULT_CONFIG)
    with path.open("rb") as f:
        data = tomllib.load(f)
    return Config.from_dict(data)


def save_config(path: Path, cfg: Config) -> None:
    path.write_bytes(tomli_w.dumps(asdict(cfg)).encode("utf-8"))


def load_groq_api_key(env_path: Path | None = None) -> str:
    """Load GROQ_API_KEY from .env or environment. Raises if missing."""
    if env_path is not None and env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv()
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key or key == "your_groq_api_key_here":
        raise RuntimeError(
            "GROQ_API_KEY is not set. Copy .env.example to .env and paste your key."
        )
    return key


def _format_toml(d: dict[str, Any]) -> str:
    return tomli_w.dumps(d)
