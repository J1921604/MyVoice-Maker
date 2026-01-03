import os
import subprocess
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw

from src.processor import _ensure_silence_mp3, combine_audio_video


def _extract_frame(ffmpeg: str, video: Path, t: float, out_png: Path) -> bytes:
    if out_png.exists():
        out_png.unlink()
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            str(t),
            "-i",
            str(video),
            "-frames:v",
            "1",
            str(out_png),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert out_png.exists() and out_png.stat().st_size > 0
    return out_png.read_bytes()


def test_webm_burned_subtitles_switch_within_slide(tmp_path: Path) -> None:
    """同一スライド内で字幕がチャンク切替することを検証する。

    concat demuxer + VFR（少フレーム）だと字幕がスライド内で更新されず、
    先頭チャンクが表示されっぱなしになる回帰を防ぐ。
    """

    # ディレクトリ構造を combine_audio_video の前提に合わせる
    out_dir = tmp_path / "output"
    temp_dir = out_dir / "temp"
    in_dir = tmp_path / "input"
    temp_dir.mkdir(parents=True)
    in_dir.mkdir(parents=True)

    # 画像 1 枚
    img = Image.new("RGB", (320, 180), (10, 12, 20))
    d = ImageDraw.Draw(img)
    d.text((10, 10), "Slide 1", fill=(240, 240, 240))
    img_path = temp_dir / "slide_000.png"
    img.save(img_path)

    # 4 秒の無音 MP3
    mp3_path = temp_dir / "slide_000.mp3"
    _ensure_silence_mp3(str(mp3_path), 4.0)

    # 句読点で 2 チャンクになる原稿
    (in_dir / "原稿.csv").write_text(
        "index,script\n0,\"今回は、AIドリブン開発が必要なのか？\"\n",
        encoding="utf-8-sig",
    )

    # 速度を優先しつつ、字幕は必ず焼き込む
    old_env = dict(os.environ)
    try:
        os.environ["USE_VP8"] = "1"
        os.environ["OUTPUT_FPS"] = "5"

        webm_path = Path(combine_audio_video(str(out_dir), resolution=320, output_name="sample", subtitle=True))
        assert webm_path.exists() and webm_path.stat().st_size > 0

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

        # 同一スライド内の別時刻でフレームが変化する（=字幕が切り替わる）こと
        f1 = _extract_frame(ffmpeg, webm_path, 0.5, out_dir / "f1.png")
        f2 = _extract_frame(ffmpeg, webm_path, 2.5, out_dir / "f2.png")
        assert f1 != f2, "字幕がスライド内で切り替わっていない可能性があります"
    finally:
        os.environ.clear()
        os.environ.update(old_env)
