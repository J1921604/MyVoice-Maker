from __future__ import annotations

from pathlib import Path

from src.voice.voice_generator import load_script_csv


def test_load_script_csv_requires_columns(tmp_path: Path) -> None:
    """必須列が無い場合は分かりやすく失敗すること。"""
    p = tmp_path / "原稿.csv"
    p.write_text("foo,bar\n1,2\n", encoding="utf-8")

    try:
        load_script_csv(p)
        assert False, "expected ValueError"
    except ValueError as e:
        msg = str(e).lower()
        assert "index" in msg and "script" in msg
