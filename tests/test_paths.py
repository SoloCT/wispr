"""Tests for resource_path / user_data_dir resolution under dev,
PyInstaller-bundled, and missing-APPDATA conditions."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from wispr_clone import paths as paths_module


def _reload_paths(monkeypatch=None) -> object:
    return importlib.reload(paths_module)


def test_resource_path_dev_resolves_relative_to_repo_root(monkeypatch):
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    p = paths_module.resource_path("assets/foo.png")
    # In dev, paths.py lives at <repo>/src/wispr_clone/paths.py
    expected_root = Path(paths_module.__file__).resolve().parent.parent.parent
    assert p == expected_root / "assets" / "foo.png"


def test_resource_path_uses_meipass_when_set(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    p = paths_module.resource_path("assets/foo.png")
    assert p == tmp_path / "assets" / "foo.png"


def test_user_data_dir_uses_appdata(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    d = paths_module.user_data_dir()
    assert d == tmp_path / paths_module.APP_NAME
    assert d.exists()


def test_user_data_dir_creates_directory(monkeypatch, tmp_path):
    appdata = tmp_path / "Roaming"
    monkeypatch.setenv("APPDATA", str(appdata))
    assert not appdata.exists()
    d = paths_module.user_data_dir()
    assert d.exists() and d.is_dir()


def test_user_data_dir_falls_back_when_appdata_missing(monkeypatch):
    monkeypatch.delenv("APPDATA", raising=False)
    d = paths_module.user_data_dir()
    # Falls back to repo root next to source tree.
    expected_root = Path(paths_module.__file__).resolve().parent.parent.parent
    assert d == expected_root


def test_user_paths_share_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    base = paths_module.user_data_dir()
    assert paths_module.user_config_path() == base / "config.toml"
    assert paths_module.user_log_path() == base / "wispr-clone.log"


def test_user_dictionary_path_per_language(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    base = paths_module.user_data_dir()
    assert paths_module.user_dictionary_path("en") == base / "dictionary-en.txt"
    assert paths_module.user_dictionary_path("yue") == base / "dictionary-yue.txt"


def test_user_dictionary_path_default_is_en(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    base = paths_module.user_data_dir()
    assert paths_module.user_dictionary_path() == base / "dictionary-en.txt"


def test_legacy_dictionary_path(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    base = paths_module.user_data_dir()
    assert paths_module.legacy_dictionary_path() == base / "dictionary.txt"
