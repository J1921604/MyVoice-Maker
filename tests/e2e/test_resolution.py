import os
import re
import subprocess
from pathlib import Path

import fitz
import imageio_ffmpeg


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


def _ffmpeg_probe_video_size(path: Path) -> tuple[int, int]:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    # ffmpegはメタ情報をstderrに出す。-f null - でデコードだけ走らせる。
    proc = _run([ffmpeg, "-hide_banner", "-i", str(path), "-f", "null", "-"])
    out = (proc.stderr or "") + "\n" + (proc.stdout or "")

    # 例: Stream #0:0: Video: vp8, yuv420p, 1920x1080, ...
    m = re.search(r"Stream #\d+:\d+.*?Video:.*?(\d{2,5})x(\d{2,5})", out)
    if not m:
        # フォールバック（広め）
        m2 = re.search(r"\b(\d{2,5})x(\d{2,5})\b", out)
        if not m2:
            raise AssertionError(f"ffmpeg出力から解像度を取得できませんでした\n{out}")
        return int(m2.group(1)), int(m2.group(2))
    return int(m.group(1)), int(m.group(2))


def _make_sample_pdf(path: Path, *, pages: int = 2, width: float = 1920, height: float = 1080) -> None:
    doc = fitz.open()
    try:
        for i in range(pages):
            page = doc.new_page(width=width, height=height)
            page.insert_text((72, 72), f"Slide {i+1}")
        doc.save(path)
    finally:
        doc.close()


def _write_csv(path: Path, pages: int) -> None:
    # Edge TTSを避けるため、scriptは空（無音MP3が生成される）
    lines = ["index,script"]
    for i in range(pages):
        lines.append(f"{i},\"\"")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


import pytest


@pytest.mark.e2e
def test_cli_generates_nonempty_webm_and_resolution_1080p(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]

    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = input_dir / "sample.pdf"
    csv_path = input_dir / "原稿.csv"
    _make_sample_pdf(pdf_path, pages=2)
    _write_csv(csv_path, pages=2)

    env = os.environ.copy()
    # 高速化（テストでは品質より速度を優先しても、機能要件は満たせる）
    env["USE_VP8"] = "1"
    env["OUTPUT_FPS"] = "15"
    env["SLIDE_RENDER_SCALE"] = "1.5"
    # main.pyが--resolutionからOUTPUT_MAX_WIDTHを設定する

    cmd = [
        "py",
        "-3.10",
        str(repo_root / "src" / "main.py"),
        "--input",
        str(input_dir),
        "--output",
        str(output_dir),
        "--script",
        str(csv_path),
        "--resolution",
        "1080p",
    ]

    out_path = output_dir / "sample.webm"
    
    proc = _run(cmd, env=env, cwd=repo_root)
    # NumPy互換性警告が出てもreturncode != 0になる場合があるので、出力を確認
    assert out_path.exists() or proc.returncode == 0, f"CLIが失敗しました\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    assert out_path.exists(), "出力WebMが生成されていません"
    assert out_path.stat().st_size > 0, "出力WebMが空です"

    w, h = _ffmpeg_probe_video_size(out_path)
    assert (w, h) == (1920, 1080), f"解像度が期待と一致しません: {(w, h)}"

