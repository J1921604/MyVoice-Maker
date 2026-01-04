from __future__ import annotations

from pathlib import Path

from src.voice.voice_generator import load_script_csv, pick_default_speaker_wav


def test_load_script_csv_decodes_cp932(tmp_path: Path) -> None:
    """Shift_JIS/CP932で保存されたCSVでも文字化けしないこと。"""
    csv_text = "index,script\n0,\"こんにちは、世界\"\n"
    p = tmp_path / "原稿.csv"
    p.write_bytes(csv_text.encode("cp932"))

    rows = load_script_csv(p)
    assert len(rows) == 1
    assert rows[0].index == 0
    assert "こんにちは" in rows[0].script


def test_pick_default_speaker_wav_prefers_numbered(tmp_path: Path) -> None:
    """sample_XX.wav がある場合は最大番号を優先すること。"""
    samples = tmp_path / "samples"
    samples.mkdir(parents=True)
    (samples / "sample.wav").write_bytes(b"x")
    (samples / "sample_01.wav").write_bytes(b"x")
    (samples / "sample_02.wav").write_bytes(b"x")

    picked = pick_default_speaker_wav(samples)
    assert picked is not None
    assert picked.name == "sample_02.wav"
