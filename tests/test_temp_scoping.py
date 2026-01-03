import os
import subprocess
from pathlib import Path

import imageio_ffmpeg
from PIL import Image

from src.processor import _ensure_silence_mp3, combine_audio_video


def _extract_frame_to_png(video: Path, t: float, out_png: Path) -> None:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
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


def test_combine_audio_video_prefers_scoped_temp_dir(tmp_path: Path) -> None:
    """output/temp/<output_name>/ があれば、従来の output/temp より優先されること。

    PDF切替などで output/temp に旧ファイルが残っていても、
    output_name ごとに分離されたtempを優先して混在を防ぐ。
    """

    out_dir = tmp_path / "output"
    temp_root = out_dir / "temp"
    temp_scoped = temp_root / "foo"
    in_dir = tmp_path / "input"
    temp_root.mkdir(parents=True)
    temp_scoped.mkdir(parents=True)
    in_dir.mkdir(parents=True)

    # ルートtempには「間違い」画像
    wrong = Image.new("RGB", (160, 90), (255, 0, 0))
    wrong.save(temp_root / "slide_000.png")
    _ensure_silence_mp3(str(temp_root / "slide_000.mp3"), 1.0)

    # scoped tempには「正しい」画像
    right = Image.new("RGB", (160, 90), (0, 255, 0))
    right.save(temp_scoped / "slide_000.png")
    _ensure_silence_mp3(str(temp_scoped / "slide_000.mp3"), 1.0)

    # 字幕OFF（CSVは不要だが、combine側のパス探索が走っても問題ないように空で用意）
    (in_dir / "原稿.csv").write_text("index,script\n0,\n", encoding="utf-8-sig")

    old_env = dict(os.environ)
    try:
        os.environ["USE_VP8"] = "1"
        os.environ["OUTPUT_FPS"] = "2"

        webm_path = Path(
            combine_audio_video(
                str(out_dir),
                resolution=160,
                output_name="foo",
                subtitle=False,
            )
        )
        assert webm_path.exists() and webm_path.stat().st_size > 0

        # 先頭フレームの中心ピクセルが緑（scopedの画像）であること
        out_png = out_dir / "frame.png"
        # concat demuxer + 静止画VFRでは「実フレーム数が非常に少ない」ことがあるため、
        # 確実に存在する先頭フレームを抽出する。
        _extract_frame_to_png(webm_path, 0.0, out_png)
        with Image.open(out_png) as img:
            r, g, b = img.convert("RGB").getpixel((img.width // 2, img.height // 2))
        assert g > 200 and r < 80 and b < 80
    finally:
        os.environ.clear()
        os.environ.update(old_env)
