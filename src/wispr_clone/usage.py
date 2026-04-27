"""Per-dictation usage tracking.

Append-only JSONL at %APPDATA%\\wispr-clone\\usage.jsonl. One line per take,
each carrying its own pre-computed cost so historical records survive
pricing changes. The summarizer is read-only and corrupt-tolerant — the
file is user-visible and may be hand-edited.

Costs are estimates. Whisper-large-v3-turbo is billed per second of input
audio; llama-3.1-8b-instant (smart-cleanup) is billed per token. Update
PRICING when Groq's rate card changes — historical lines are unaffected
because cost_usd is frozen at write time.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


# Groq rate card snapshot. Update when it changes.
PRICING = {
    "whisper_per_audio_hour": 0.04,        # USD / hr of input audio
    "cleanup_input_per_million": 0.05,     # USD / 1M prompt tokens
    "cleanup_output_per_million": 0.08,    # USD / 1M completion tokens
}


def compute_cost_usd(
    audio_seconds: float,
    cleanup_input_tokens: int,
    cleanup_output_tokens: int,
) -> float:
    whisper = (audio_seconds / 3600.0) * PRICING["whisper_per_audio_hour"]
    cleanup_in = (cleanup_input_tokens / 1_000_000.0) * PRICING["cleanup_input_per_million"]
    cleanup_out = (cleanup_output_tokens / 1_000_000.0) * PRICING["cleanup_output_per_million"]
    return whisper + cleanup_in + cleanup_out


def record_event(
    path: Path,
    *,
    language: str,
    audio_seconds: float,
    transcript_chars: int,
    cleanup_used: bool,
    cleanup_input_tokens: int,
    cleanup_output_tokens: int,
    error: Optional[str] = None,
) -> None:
    """Append one JSONL record. Never raises; logs on failure so a broken
    usage write can never break dictation."""
    try:
        cost = compute_cost_usd(audio_seconds, cleanup_input_tokens, cleanup_output_tokens)
        record = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "lang": language,
            "audio_s": round(float(audio_seconds), 3),
            "chars": int(transcript_chars),
            "cleanup": bool(cleanup_used),
            "in_tok": int(cleanup_input_tokens),
            "out_tok": int(cleanup_output_tokens),
            "cost_usd": round(cost, 6),
            "error": error,
        }
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with path.open("a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        log.exception("usage record_event failed")


def _empty_bucket() -> dict:
    return {"count": 0, "audio_s": 0.0, "chars": 0, "cost_usd": 0.0}


def _add(bucket: dict, rec: dict) -> None:
    bucket["count"] += 1
    bucket["audio_s"] += float(rec.get("audio_s", 0.0) or 0.0)
    bucket["chars"] += int(rec.get("chars", 0) or 0)
    bucket["cost_usd"] += float(rec.get("cost_usd", 0.0) or 0.0)


def _parse_ts(s: str) -> Optional[datetime]:
    try:
        if s.endswith("Z"):
            return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def summarize(path: Path, *, now: Optional[datetime] = None) -> dict:
    """Aggregate the JSONL into totals. `now` is injectable for tests."""
    now = now if now is not None else datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    seven_days_ago = now - timedelta(days=7)

    out = {
        "all_time": _empty_bucket(),
        "last_7d": _empty_bucket(),
        "today": _empty_bucket(),
        "by_language": {},
        "error_count": 0,
    }

    if not path.exists():
        return out

    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        log.exception("usage summarize read failed")
        return out

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict):
            continue
        _add(out["all_time"], rec)
        if rec.get("error"):
            out["error_count"] += 1
        ts = _parse_ts(rec.get("ts", ""))
        if ts is not None:
            if ts >= today_start:
                _add(out["today"], rec)
            if ts >= seven_days_ago:
                _add(out["last_7d"], rec)
        lang = str(rec.get("lang", "?"))
        if lang not in out["by_language"]:
            out["by_language"][lang] = _empty_bucket()
        _add(out["by_language"][lang], rec)

    return out


def clear(path: Path) -> None:
    """Truncate the usage log. Called by the dialog's Reset button."""
    try:
        if path.exists():
            path.write_text("", encoding="utf-8")
    except OSError:
        log.exception("usage clear failed")
