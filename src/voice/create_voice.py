from __future__ import annotations

import argparse
import os
import re
import subprocess
from pathlib import Path

import imageio_ffmpeg


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _samples_dir() -> Path:
    return _repo_root() / "src" / "voice" / "models" / "samples"


def _next_sample_path(samples_dir: Path) -> Path:
    samples_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(samples_dir.glob("sample_*.wav"))
    max_n = 0
    for p in existing:
        m = re.match(r"^sample_(\d+)\.wav$", p.name, flags=re.IGNORECASE)
        if m:
            max_n = max(max_n, int(m.group(1)))
    return samples_dir / f"sample_{max_n + 1:02d}.wav"


def _ffmpeg_convert_to_wav(src_path: Path, dst_path: Path) -> None:
    """任意の音声を PCM 16-bit mono WAV(24kHz) に変換する（XTTS v2向け）。"""
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    dst_path.parent.mkdir(parents=True, exist_ok=True)

    args = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostats",
        "-i",
        str(src_path),
        "-ac",
        "1",
        "-ar",
        "24000",
        "-c:a",
        "pcm_s16le",
        str(dst_path),
    ]
    proc = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        msg = (proc.stderr or b"").decode("utf-8", errors="replace")
        raise RuntimeError(f"FFmpeg conversion failed (code={proc.returncode}): {msg}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="音声サンプル作成ユーティリティ（sample_XX.wav を追加）")
    parser.add_argument(
        "--input",
        type=str,
        default=None,
        help="変換したい音声ファイル（wav/webm/mp3/m4a等）。未指定の場合はWeb UIの録音機能を使ってください。",
    )
    args = parser.parse_args(argv)

    if not args.input:
        print("このスクリプトは '音声ファイル→sample_XX.wav 変換' 用です。")
        print("録音は Web UI（index.html の『録音』）を使うのが推奨です。")
        print("例: py -3.10 src\\voice\\create_voice.py --input path\\to\\recording.webm")
        return 2

    src = Path(args.input)
    if not src.exists():
        print(f"入力ファイルが見つかりません: {src}")
        return 2

    dst = _next_sample_path(_samples_dir())
    try:
        _ffmpeg_convert_to_wav(src, dst)
    except Exception as e:
        print(f"変換に失敗しました: {e}")
        return 1

    rel = None
    try:
        rel = dst.relative_to(_repo_root())
    except Exception:
        rel = dst
    print(f"保存しました: {rel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
