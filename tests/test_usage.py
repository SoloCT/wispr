"""Per-dictation usage tracking tests. No network; pure file IO."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from wispr_clone.usage import (
    PRICING,
    clear,
    compute_cost_usd,
    record_event,
    summarize,
)


def _read(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------------- cost arithmetic ----------------

def test_compute_cost_whisper_only():
    # 60 s of audio at $0.04/hr → $0.04 * (60/3600) = $0.000666...
    cost = compute_cost_usd(60, 0, 0)
    assert abs(cost - PRICING["whisper_per_audio_hour"] / 60.0) < 1e-9


def test_compute_cost_with_cleanup_tokens():
    cost = compute_cost_usd(60.0, 200, 100)
    expected = (
        PRICING["whisper_per_audio_hour"] / 60.0
        + 200 / 1_000_000.0 * PRICING["cleanup_input_per_million"]
        + 100 / 1_000_000.0 * PRICING["cleanup_output_per_million"]
    )
    assert abs(cost - expected) < 1e-9


def test_compute_cost_zero_for_empty_call():
    assert compute_cost_usd(0.0, 0, 0) == 0.0


# ---------------- record_event ----------------

def test_record_event_appends_jsonl_line(tmp_path: Path):
    p = tmp_path / "usage.jsonl"
    record_event(
        p,
        language="en",
        audio_seconds=12.4,
        transcript_chars=87,
        cleanup_used=True,
        cleanup_input_tokens=145,
        cleanup_output_tokens=92,
        error=None,
    )
    records = _read(p)
    assert len(records) == 1
    rec = records[0]
    assert rec["lang"] == "en"
    assert rec["audio_s"] == 12.4
    assert rec["chars"] == 87
    assert rec["cleanup"] is True
    assert rec["in_tok"] == 145
    assert rec["out_tok"] == 92
    assert rec["error"] is None
    assert rec["cost_usd"] > 0
    # ISO-ish timestamp ending in Z.
    assert rec["ts"].endswith("Z")


def test_record_event_writes_error_string(tmp_path: Path):
    p = tmp_path / "usage.jsonl"
    record_event(
        p,
        language="yue",
        audio_seconds=3.0,
        transcript_chars=0,
        cleanup_used=False,
        cleanup_input_tokens=0,
        cleanup_output_tokens=0,
        error="Transcription failed: boom",
    )
    rec = _read(p)[0]
    assert rec["error"] == "Transcription failed: boom"


def test_record_event_appends_multiple_lines(tmp_path: Path):
    p = tmp_path / "usage.jsonl"
    for i in range(3):
        record_event(
            p,
            language="en",
            audio_seconds=float(i),
            transcript_chars=i * 10,
            cleanup_used=False,
            cleanup_input_tokens=0,
            cleanup_output_tokens=0,
        )
    assert len(_read(p)) == 3


def test_record_event_swallows_io_failure(tmp_path: Path, monkeypatch):
    # Point at a non-writeable path: a directory. Should not raise.
    record_event(
        tmp_path,  # passing the directory itself — open(..., "a") raises
        language="en",
        audio_seconds=1.0,
        transcript_chars=0,
        cleanup_used=False,
        cleanup_input_tokens=0,
        cleanup_output_tokens=0,
    )
    # If we got here, the call did not raise. That's the contract.


# ---------------- summarize ----------------

def _fixed_now() -> datetime:
    return datetime(2026, 4, 27, 12, 0, 0, tzinfo=timezone.utc)


def _write_record(path: Path, ts: datetime, **fields) -> None:
    rec = {
        "ts": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lang": fields.get("lang", "en"),
        "audio_s": fields.get("audio_s", 10.0),
        "chars": fields.get("chars", 50),
        "cleanup": fields.get("cleanup", False),
        "in_tok": fields.get("in_tok", 0),
        "out_tok": fields.get("out_tok", 0),
        "cost_usd": fields.get("cost_usd", 0.001),
        "error": fields.get("error"),
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def test_summarize_empty_file_returns_zero_buckets(tmp_path: Path):
    p = tmp_path / "usage.jsonl"
    summary = summarize(p, now=_fixed_now())
    assert summary["all_time"]["count"] == 0
    assert summary["today"]["count"] == 0
    assert summary["last_7d"]["count"] == 0
    assert summary["by_language"] == {}
    assert summary["error_count"] == 0


def test_summarize_aggregates_totals(tmp_path: Path):
    p = tmp_path / "usage.jsonl"
    now = _fixed_now()
    _write_record(p, now - timedelta(hours=1), lang="en", audio_s=30.0, chars=100, cost_usd=0.001)
    _write_record(p, now - timedelta(hours=2), lang="yue", audio_s=20.0, chars=40, cost_usd=0.002)
    _write_record(p, now - timedelta(hours=3), lang="en", audio_s=10.0, chars=20, cost_usd=0.0005)
    summary = summarize(p, now=now)
    assert summary["all_time"]["count"] == 3
    assert abs(summary["all_time"]["audio_s"] - 60.0) < 1e-9
    assert summary["all_time"]["chars"] == 160
    assert abs(summary["all_time"]["cost_usd"] - 0.0035) < 1e-9


def test_summarize_today_window(tmp_path: Path):
    p = tmp_path / "usage.jsonl"
    now = _fixed_now()  # 2026-04-27 12:00 UTC
    _write_record(p, now - timedelta(hours=1))                       # today
    _write_record(p, now - timedelta(hours=18))                      # yesterday
    _write_record(p, now.replace(hour=0, minute=0, second=1))        # today, just after midnight
    summary = summarize(p, now=now)
    assert summary["today"]["count"] == 2
    assert summary["last_7d"]["count"] == 3


def test_summarize_seven_day_window(tmp_path: Path):
    p = tmp_path / "usage.jsonl"
    now = _fixed_now()
    _write_record(p, now - timedelta(days=2))
    _write_record(p, now - timedelta(days=6, hours=23))
    _write_record(p, now - timedelta(days=8))    # outside 7d
    _write_record(p, now - timedelta(days=30))   # outside 7d
    summary = summarize(p, now=now)
    assert summary["last_7d"]["count"] == 2
    assert summary["all_time"]["count"] == 4


def test_summarize_per_language_breakdown(tmp_path: Path):
    p = tmp_path / "usage.jsonl"
    now = _fixed_now()
    _write_record(p, now, lang="en", audio_s=10.0, cost_usd=0.001)
    _write_record(p, now, lang="en", audio_s=20.0, cost_usd=0.002)
    _write_record(p, now, lang="yue", audio_s=5.0, cost_usd=0.0005)
    summary = summarize(p, now=now)
    assert summary["by_language"]["en"]["count"] == 2
    assert abs(summary["by_language"]["en"]["audio_s"] - 30.0) < 1e-9
    assert summary["by_language"]["yue"]["count"] == 1


def test_summarize_skips_corrupt_lines(tmp_path: Path):
    p = tmp_path / "usage.jsonl"
    now = _fixed_now()
    _write_record(p, now, audio_s=10.0, cost_usd=0.001)
    with p.open("a", encoding="utf-8") as f:
        f.write("not-json garbage\n")
        f.write("{partial json\n")
        f.write("\n")  # blank line
    _write_record(p, now, audio_s=20.0, cost_usd=0.002)
    summary = summarize(p, now=now)
    assert summary["all_time"]["count"] == 2
    assert abs(summary["all_time"]["audio_s"] - 30.0) < 1e-9


def test_summarize_counts_errors(tmp_path: Path):
    p = tmp_path / "usage.jsonl"
    now = _fixed_now()
    _write_record(p, now, error=None)
    _write_record(p, now, error="Transcription failed: 401")
    _write_record(p, now, error="Paste failed: foo")
    summary = summarize(p, now=now)
    assert summary["error_count"] == 2


# ---------------- clear ----------------

def test_clear_truncates_file(tmp_path: Path):
    p = tmp_path / "usage.jsonl"
    _write_record(p, _fixed_now())
    assert p.read_text(encoding="utf-8") != ""
    clear(p)
    assert p.read_text(encoding="utf-8") == ""


def test_clear_handles_missing_file(tmp_path: Path):
    p = tmp_path / "doesnotexist.jsonl"
    clear(p)  # must not raise
    assert not p.exists()
