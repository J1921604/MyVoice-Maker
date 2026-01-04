from __future__ import annotations

import os
import subprocess
import sys
import wave
from pathlib import Path

import pytest


def _run(cmd: list[str], *, env: dict[str, str] | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _write_wav(path: Path, *, seconds: float = 0.3, sr: int = 24000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = int(seconds * sr)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(b"\x00\x00" * frames)


@pytest.mark.e2e
def test_cli_generates_mp3_from_csv(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]

    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_path = input_dir / "原稿.csv"
    csv_path.write_text("index,script\n0,\"テストです\"\n", encoding="utf-8-sig")

    speaker = tmp_path / "speaker.wav"
    _write_wav(speaker)

    env = os.environ.copy()
    env["SVM_FAKE_TTS"] = "1"  # モデルDL無しで完走させる

    cmd = [
        sys.executable,
        str(repo_root / "src" / "main.py"),
        "--script",
        str(csv_path),
        "--output",
        str(output_dir),
        "--speaker-wav",
        str(speaker),
    ]

    proc = _run(cmd, env=env, cwd=repo_root)
    assert proc.returncode == 0, f"CLIが失敗しました\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"

    out_mp3 = output_dir / "slide_000.mp3"
    assert out_mp3.exists(), "MP3が生成されていません"
    assert out_mp3.stat().st_size > 0, "MP3が空です"

