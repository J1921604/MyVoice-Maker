import os
import subprocess
import wave
import contextlib
import shutil
import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

# PIL.Image.ANTIALIAS互換性修正（Pillow 10+対応）
from PIL import Image
if not hasattr(Image, 'ANTIALIAS'):
    Image.ANTIALIAS = Image.Resampling.LANCZOS

import imageio_ffmpeg


def _patch_torchaudio_load() -> None:
    """torchaudio.load を soundfile ベースに差し替えて TorchCodec 依存を回避する。

    TorchCodec は Windows で FFmpeg の shared DLL を要求し、環境が整っていないと
    「Could not load libtorchcodec」などのエラーを誘発する。Coqui TTS 内部で
    torchaudio.load が呼ばれるため、事前に soundfile 実装へ置き換えておく。
    """

    try:
        import soundfile as sf
        import torchaudio
        import torch
    except ImportError as e:  # pragma: no cover - 実行環境の不足を明示
        raise RuntimeError(
            "torchaudio/soundfile の読み込みに失敗しました。requirements.txt を再インストールしてください。"
        ) from e

    def patched_load(filepath, *args, **kwargs):
        audio_data, sample_rate = sf.read(filepath)
        if audio_data.ndim == 1:
            audio_tensor = torch.from_numpy(audio_data).unsqueeze(0)
        else:
            audio_tensor = torch.from_numpy(audio_data.T)
        return audio_tensor.float(), sample_rate

    # 既存の load を置換（元の関数は保持しない。TorchCodec を経由しないことを優先）
    torchaudio.load = patched_load
    print("TorchCodecバイパス: torchaudio.load を soundfile ベースに差し替えました")


def _read_script_csv(script_path: str) -> dict[int, str]:
    """原稿CSV（index,script）を辞書化して返す。

    - UTF-8(BOMあり/なし) + cp932/shift_jis を順に試す
    - pandas依存を避け、pytest収集や軽量環境での安定性を上げる
    """
    last_err: Exception | None = None
    for enc in ("utf-8-sig", "utf-8", "cp932", "shift_jis"):
        try:
            with open(script_path, "r", encoding=enc, newline="") as f:
                reader = csv.DictReader(f)
                # ヘッダ正規化
                fieldnames = [str(n).strip() for n in (reader.fieldnames or [])]
                # DictReaderは fieldnames を固定して持つため、ここで差し替える
                reader.fieldnames = fieldnames

                if "index" not in fieldnames or "script" not in fieldnames:
                    raise ValueError("Script CSV must have columns: index, script")

                out: dict[int, str] = {}
                for row in reader:
                    try:
                        raw_idx = row.get("index", "")
                        idx = int(str(raw_idx).strip())
                    except Exception:
                        continue

                    script = row.get("script", "")
                    out[idx] = "" if script is None else str(script)
                return out
        except UnicodeDecodeError as e:
            last_err = e
            continue
        except Exception as e:
            last_err = e
            continue

    if last_err is not None:
        raise last_err
    return {}


@dataclass
class _SlideItem:
    page_index: int
    image_path: str
    audio_path: str
    script_text: str
    duration: float


def clear_temp_folder(temp_dir: str) -> bool:
    """tempフォルダを削除して再作成（上書き更新）。

    Returns:
        bool: 成功した場合True、エラーが発生した場合False
    """
    max_retries = 3
    for attempt in range(max_retries):
        try:
            if os.path.exists(temp_dir):
                # ファイルハンドルを解放するため、明示的にガベージコレクション
                import gc
                gc.collect()
                
                # 再帰的に削除
                shutil.rmtree(temp_dir, ignore_errors=False, onerror=_remove_readonly)
                print(f"Cleared temp folder: {temp_dir}")
            os.makedirs(temp_dir, exist_ok=True)
            return True
        except PermissionError as e:
            if attempt < max_retries - 1:
                print(f"Retry {attempt + 1}/{max_retries}: Could not clear temp folder (file locked): {e}")
                import time
                time.sleep(0.5)
                continue
            else:
                print(f"Warning: Could not clear temp folder after {max_retries} attempts (file locked): {e}")
                # ロックされていても続行
                os.makedirs(temp_dir, exist_ok=True)
                return False
        except Exception as e:
            print(f"Warning: Error clearing temp folder: {e}")
            os.makedirs(temp_dir, exist_ok=True)
            return False
    return False


def _remove_readonly(func, path, excinfo):
    """読み取り専用ファイルを削除できるようにする"""
    import stat
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _get_render_scale() -> float:
    """PDFを画像化する倍率。高すぎると遅く/重くなるため環境変数で調整可能にする。"""
    try:
        return float(os.environ.get("SLIDE_RENDER_SCALE", "1.5"))
    except Exception:
        return 1.5


def _get_output_max_width() -> int:
    """出力動画の最大幅。大きいほど高品質だがエンコードは遅い。"""
    try:
        return int(os.environ.get("OUTPUT_MAX_WIDTH", "1280"))
    except Exception:
        return 1280


def _get_output_fps() -> int:
    """静止画ベースの動画。字幕切り替わりを確実にするため30fps推奨。"""
    try:
        return int(os.environ.get("OUTPUT_FPS", "30"))
    except Exception:
        return 30


def _get_vp9_cpu_used() -> int:
    """VP9速度パラメータ(0-8程度)。大きいほど速いが画質低下。最大8で高速化。"""
    try:
        return int(os.environ.get("VP9_CPU_USED", "8"))
    except Exception:
        return 8


def _get_vp9_crf() -> int:
    """VP9品質パラメータ。大きいほど軽い（低画質）。"""
    try:
        return int(os.environ.get("VP9_CRF", "40"))
    except Exception:
        return 40


def _get_use_vp8() -> bool:
    """VP8を使用（VP9より高速だがやや低品質）。"""
    try:
        return os.environ.get("USE_VP8", "1") == "1"
    except Exception:
        return True


def _get_silence_slide_duration() -> float:
    """原稿が空のページを何秒表示するか。"""
    try:
        return float(os.environ.get("SILENCE_SLIDE_DURATION", "5"))
    except Exception:
        return 5.0


def _file_exists_nonempty(path: str) -> bool:
    try:
        return os.path.exists(path) and os.path.getsize(path) > 0
    except Exception:
        return False


def _write_concat_list(paths: List[str], durations: Optional[List[float]], out_path: str) -> None:
    """FFmpeg concat demuxer list を書き出す。

    - durations は paths と同じ長さを想定。
    - durations を指定する場合、仕様上「最後のファイルは duration 行なし」が安全なため、
      最後のファイルを再掲して終端を作る。
    - durations が None（例: 音声側）では、末尾の再掲は行わない。
      ※末尾を重複させると最後の音声が二重に再生されてしまう。
    """

    def q(p: str) -> str:
        # concat demuxer は forward slash の方が安全
        p2 = os.path.abspath(p).replace("\\", "/")
        return p2.replace("'", "\\'")

    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        for idx, p in enumerate(paths):
            f.write(f"file '{q(p)}'\n")
            if durations is not None:
                # concat demuxer の duration は「直前の file」に適用される。
                # 最後のファイルにも duration を効かせるには、duration 行を書いたあと
                # 終端用に最後の file を再掲する必要がある。
                d = float(durations[idx])
                if d <= 0:
                    d = 0.01
                f.write(f"duration {d:.6f}\n")

        # durations を書いた場合は、終端用に最後のファイルを再掲する
        # (audio 側のように durations が無い場合は再掲しない)
        if paths and durations is not None:
            f.write(f"file '{q(paths[-1])}'\n")


def _ensure_silence_wav(path: str, duration: float, sample_rate: int = 48000) -> None:
    if _file_exists_nonempty(path):
        return
    if duration <= 0:
        duration = 0.01
    n_samples = int(sample_rate * duration)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with contextlib.closing(wave.open(path, "wb")) as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * n_samples)


def _ensure_silence_mp3(path: str, duration: float, sample_rate: int = 24000) -> None:
    """FFmpegで無音MP3を生成する（concat demuxerで混在を避けるため）。"""
    if _file_exists_nonempty(path):
        return
    if duration <= 0:
        duration = 0.01

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    args = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"anullsrc=r={int(sample_rate)}:cl=mono",
        "-t",
        f"{float(duration):.6f}",
        "-c:a",
        "libmp3lame",
        "-q:a",
        "9",
        path,
    ]

    proc = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        stderr = proc.stderr or b""
        try:
            msg = stderr.decode("utf-8")
        except Exception:
            msg = stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"Failed to generate silence mp3: {msg}")


def _get_audio_duration_seconds(path: str) -> float:
    """音声長(秒)を取得する。

    速度改善のため、まずはFFmpegのヘッダ出力（Duration行）をパースして取得する。
    取得に失敗した場合のみ MoviePy にフォールバックする。
    """

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    try:
        # ffmpeg は出力未指定だと returncode!=0 になるが、Duration は stderr に出る
        proc = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stderr = proc.stderr or b""
        try:
            text = stderr.decode("utf-8")
        except Exception:
            text = stderr.decode("utf-8", errors="replace")

        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
        if m:
            h = int(m.group(1))
            mi = int(m.group(2))
            s = float(m.group(3))
            dur = h * 3600 + mi * 60 + s
            if dur > 0:
                return float(dur)
    except Exception:
        # fall back
        pass

    # moviepy は import が重い/環境差で遅延しやすいので遅延importする。
    from moviepy.editor import AudioFileClip

    clip = None
    try:
        clip = AudioFileClip(path)
        return float(clip.duration or 0)
    finally:
        if clip is not None:
            try:
                clip.close()
            except Exception:
                pass


def _render_webm_with_ffmpeg(
    slides: List[_SlideItem],
    output_path: str,
    temp_dir: str,
    subtitle_path: str = None,
) -> None:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    fps = _get_output_fps()
    max_w = _get_output_max_width()
    cpu_used = _get_vp9_cpu_used()
    crf = _get_vp9_crf()
    use_vp8 = _get_use_vp8()
    threads = str(os.cpu_count() or 4)

    video_list = os.path.join(temp_dir, "__video_concat.txt")
    audio_list = os.path.join(temp_dir, "__audio_concat.txt")

    image_paths = [s.image_path for s in slides]
    audio_paths = [s.audio_path for s in slides]
    durations = [s.duration for s in slides]

    _write_concat_list(image_paths, durations, video_list)
    _write_concat_list(audio_paths, None, audio_list)

    # 重要:
    # concat demuxer + VFRだと「各スライド=少数フレーム」になりやすく、
    # 焼き込み字幕(subtitles/ass)はフレーム更新が無いとテキストも切り替わらない。
    # そのため、fpsフィルタでCFR相当のフレームを生成してから字幕を焼き込む。
    vf_parts: List[str] = []

    # 出力を16:9に揃え、余白はグレー背景でパディング（字幕の視認性も上がる）
    max_h = int(round(max_w * 9 / 16))

    has_subtitles = bool(subtitle_path and os.path.exists(subtitle_path))
    if has_subtitles:
        # concat demuxer + VFR（少フレーム）だと字幕がスライド内で更新されないため、
        # まずCFR相当のフレームを作ってから字幕を焼き込む。
        vf_parts.append(f"fps={fps}")

    # 高速化: bilinearよりfast_bilinearを使用
    # force_original_aspect_ratio=decrease で縦横比を維持して16:9に収め、padでグレー背景を付ける
    vf_parts.append(f"scale={max_w}:{max_h}:force_original_aspect_ratio=decrease:flags=fast_bilinear")
    vf_parts.append(f"pad={max_w}:{max_h}:(ow-iw)/2:(oh-ih)/2:color=0x303030")

    if has_subtitles:
        # Windowsドライブレターの ':' は libass/subtitles フィルタでエスケープが必要
        abs_sub = os.path.abspath(subtitle_path).replace('\\', '/').replace(':', '\\:')
        vf_parts.append(f"subtitles='{abs_sub}'")

    vf_parts.append("format=yuv420p")
    vf = ",".join(vf_parts)

    if use_vp8:
        # VP8は高速だがやや低品質
        args = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostats",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            video_list,
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            audio_list,
            "-vf",
            vf,
            "-c:v",
            "libvpx",  # VP8
            "-deadline",
            "realtime",
            "-cpu-used",
            str(min(cpu_used, 16)),
            "-threads",
            threads,
            "-b:v",
            "1M",
            "-qmin",
            "4",
            "-qmax",
            "50",
            "-c:a",
            # WebMはVP8+Opusも一般に再生可能（音声はOpusの方が軽量/高速なことが多い）
            "libopus",
            "-b:a",
            "64k",
            "-vbr",
            "on",
            "-shortest",
            output_path,
        ]
    else:
        # VP9（より高品質だが遅い）
        args = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostats",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            video_list,
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            audio_list,
            "-vf",
            vf,
            "-c:v",
            "libvpx-vp9",
            "-deadline",
            "realtime",
            "-cpu-used",
            str(cpu_used),
            "-row-mt",
            "1",
            "-threads",
            threads,
            "-b:v",
            "0",
            "-crf",
            str(crf),
            "-c:a",
            "libopus",
            "-b:a",
            "64k",
            "-vbr",
            "on",
            "-shortest",
            output_path,
        ]

    print(f"FFmpeg: {ffmpeg}")
    print(f"Encoding with {'VP8' if use_vp8 else 'VP9'} (high-speed mode)...")
    proc = subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        stderr = proc.stderr or b""
        stdout = proc.stdout or b""

        # まずutf-8で読んでダメならcp932、最後はreplace
        def safe_decode(b: bytes) -> str:
            for enc in ("utf-8", "cp932"):
                try:
                    return b.decode(enc)
                except Exception:
                    continue
            return b.decode("utf-8", errors="replace")

        err = (safe_decode(stderr) or safe_decode(stdout)).strip()
        raise RuntimeError(f"FFmpeg failed (code={proc.returncode}): {err}")


def _render_mp4_with_ffmpeg(
    slides: List[_SlideItem],
    output_path: str,
    temp_dir: str,
    subtitle_path: str = None,
) -> None:
    """静止画+音声からMP4(H.264/AAC)を生成する。"""
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    fps = _get_output_fps()
    max_w = _get_output_max_width()
    threads = str(os.cpu_count() or 4)

    video_list = os.path.join(temp_dir, "__video_concat.txt")
    audio_list = os.path.join(temp_dir, "__audio_concat.txt")

    image_paths = [s.image_path for s in slides]
    audio_paths = [s.audio_path for s in slides]
    durations = [s.duration for s in slides]

    _write_concat_list(image_paths, durations, video_list)
    _write_concat_list(audio_paths, None, audio_list)

    vf_parts: List[str] = []

    max_h = int(round(max_w * 9 / 16))
    has_subtitles = bool(subtitle_path and os.path.exists(subtitle_path))
    if has_subtitles:
        vf_parts.append(f"fps={fps}")

    vf_parts.append(f"scale={max_w}:{max_h}:force_original_aspect_ratio=decrease:flags=fast_bilinear")
    vf_parts.append(f"pad={max_w}:{max_h}:(ow-iw)/2:(oh-ih)/2:color=0x303030")

    if has_subtitles:
        abs_sub = os.path.abspath(subtitle_path).replace('\\', '/').replace(':', '\\:')
        vf_parts.append(f"subtitles='{abs_sub}'")

    vf_parts.append("format=yuv420p")
    vf = ",".join(vf_parts)

    args = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostats",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        video_list,
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        audio_list,
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-threads",
        threads,
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        "-shortest",
        output_path,
    ]

    print(f"FFmpeg: {ffmpeg}")
    print("Encoding MP4 (H.264/AAC, high-speed mode)...")
    proc = subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        stderr = proc.stderr or b""

        def safe_decode(b: bytes) -> str:
            for enc in ("utf-8", "cp932"):
                try:
                    return b.decode(enc)
                except Exception:
                    continue
            return b.decode("utf-8", errors="replace")

        err = safe_decode(stderr).strip()
        raise RuntimeError(f"FFmpeg failed (code={proc.returncode}): {err}")


def _embed_subtitles(input_path: str, subtitle_path: str, output_path: str) -> None:
    """動画に字幕を埋め込む"""
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    cpu_used = _get_vp9_cpu_used()
    crf = _get_vp9_crf()
    use_vp8 = _get_use_vp8()
    threads = str(os.cpu_count() or 4)
    
    # Windows用にパスをエスケープ
    escaped_path = subtitle_path.replace('\\', '/').replace(':', '\\:')
    fps = _get_output_fps()
    # _render_webm_with_ffmpeg と同様、字幕はフレーム更新がないと切り替わらないため
    # fps→subtitles の順で適用する。
    vf = f"fps={fps},subtitles='{escaped_path}'"
    
    print(f"Embedding subtitles...")
    
    if use_vp8:
        args = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel", "error",
            "-nostats",
            "-i", input_path,
            "-vf", vf,
            "-c:v", "libvpx",
            "-deadline", "realtime",
            "-cpu-used", str(min(cpu_used, 16)),
            "-threads", threads,
            "-b:v", "1M",
            "-qmin", "4",
            "-qmax", "50",
            "-c:a", "copy",
            output_path,
        ]
    else:
        args = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel", "error",
            "-nostats",
            "-i", input_path,
            "-vf", vf,
            "-c:v", "libvpx-vp9",
            "-deadline", "realtime",
            "-cpu-used", str(cpu_used),
            "-row-mt", "1",
            "-threads", threads,
            "-b:v", "0",
            "-crf", str(crf),
            "-c:a", "copy",
            output_path,
        ]
    
    proc = subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        stderr = proc.stderr or b""
        def safe_decode(b: bytes) -> str:
            for enc in ("utf-8", "cp932"):
                try:
                    return b.decode(enc)
                except Exception:
                    continue
            return b.decode("utf-8", errors="replace")
        err = safe_decode(stderr).strip()
        raise RuntimeError(f"FFmpeg subtitle embedding failed (code={proc.returncode}): {err}")


async def generate_voice(text, output_path, voice="ja-JP-NanamiNeural", use_coqui=True):
    """Coqui TTS で音声を生成する（Edge TTS へのフォールバックは無効化）。

    Args:
        text: 音声化するテキスト
        output_path: 出力ファイルパス
        voice: 互換性のため残すが、現在は未使用
        use_coqui: 環境変数 USE_COQUI_TTS と掛け合わせて制御
    """

    use_coqui_env = os.environ.get("USE_COQUI_TTS", "1") == "1"
    if not (use_coqui and use_coqui_env):
        raise RuntimeError(
            "Coqui TTS が無効化されています。USE_COQUI_TTS=1 を設定し、Coquiモデルを利用してください。"
        )
    
    # テキストが長すぎる場合は分割して生成（タイムアウト対策）
    max_length = 500
    if len(text) > max_length:
        import tempfile
        segments = [text[i:i+max_length] for i in range(0, len(text), max_length)]
        temp_files = []
        
        for i, segment in enumerate(segments):
            temp_file = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
            temp_files.append(temp_file.name)
            temp_file.close()
            await generate_voice(segment, temp_file.name, voice, use_coqui)
        
        # 複数の音声ファイルを結合
        _concatenate_audio_files(temp_files, output_path)
        
        # 一時ファイルを削除
        for temp_file in temp_files:
            try:
                os.remove(temp_file)
            except:
                pass
        return

    # 話者サンプル WAV（デフォルトは自録りファイル）
    repo_root = Path(__file__).resolve().parent
    default_sample = repo_root / "voice" / "models" / "samples" / "sample.wav"
    speaker_wav = Path(os.environ.get("COQUI_SPEAKER_WAV", default_sample))

    if not speaker_wav.exists():
        raise FileNotFoundError(
            f"話者サンプルが見つかりません: {speaker_wav}\n"
            "src/voice/create_voice.py を実行し、自分の声を録音してください。"
        )

    try:
        # キャッシュされたTTSモデルを取得（初回のみロード）
        tts = _get_tts_model()
        
        print(f"Generating voice with Coqui TTS: {text[:50]}...")
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        tts.tts_to_file(
            text=text,
            speaker_wav=str(speaker_wav),
            language="ja",
            file_path=output_path,
        )
        print(f"Voice generated: {output_path}")
    except OSError as e:
        # TorchCodec が見つからない場合に明示的なメッセージを出す
        msg = str(e)
        if "torchcodec" in msg.lower():
            raise RuntimeError(
                "TorchCodec の読み込みに失敗しました。FFmpeg full-shared 版を導入し、"
                "docs/ffmpegインストール手順.md の手順で PATH を設定してください。"
            ) from e
        raise
    except Exception:
        # 例外を握りつぶさず、そのまま上位へ投げる（Edge TTS にはフォールバックしない）
        raise


def _concatenate_audio_files(input_files: List[str], output_path: str) -> None:
    """複数の音声ファイルを結合する（FFmpeg使用）"""
    import tempfile
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    
    # concat用のリストファイルを作成
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
        concat_file = f.name
        for input_file in input_files:
            # FFmpegのconcat demuxer用にパスをエスケープ
            escaped = input_file.replace('\\', '/').replace("'", "\\'")
            f.write(f"file '{escaped}'\n")
    
    try:
        args = [
            ffmpeg,
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_file,
            "-c", "copy",
            output_path
        ]
        proc = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            raise RuntimeError(f"Audio concatenation failed: {proc.stderr.decode('utf-8', errors='replace')}")
    finally:
        try:
            os.remove(concat_file)
        except:
            pass


async def generate_single_audio(
    slide_index: int,
    script: str,
    output_dir: str,
    temp_dir: Optional[str] = None,
) -> str:
    """単一スライドの音声を生成してファイルパスを返す。

    Args:
        slide_index: スライド番号
        script: 原稿
        output_dir: 出力ディレクトリ
        temp_dir: 保存先tempディレクトリ（指定がなければ output_dir/temp）
    """
    base_temp_dir = temp_dir or os.path.join(output_dir, "temp")
    os.makedirs(base_temp_dir, exist_ok=True)

    audio_path = os.path.join(base_temp_dir, f"slide_{slide_index:03d}.mp3")

    if script and script.strip():
        await generate_voice(script.strip(), audio_path)
        return audio_path
    return ""



def _select_temp_dir(output_dir: str, output_name: str, temp_subdir: Optional[str] = None) -> str:
    """動画生成に使う temp ディレクトリを決める。

    互換性のため、まず output/temp/<subdir>（または output_name）を優先し、
    無ければ従来の output/temp を使う。
    """
    base = os.path.join(output_dir, "temp")
    if temp_subdir:
        cand = os.path.join(base, temp_subdir)
        if os.path.isdir(cand):
            return cand

    cand2 = os.path.join(base, output_name)
    if os.path.isdir(cand2):
        return cand2

    return base


# Coqui TTSのグローバルキャッシュ（初回初期化のみ実行）
_tts_cache = None
_tts_cache_lock = None


def _get_tts_model():
    """Coqui TTSモデルのシングルトンを取得する。初回のみモデルロードを行う。"""
    global _tts_cache, _tts_cache_lock
    
    if _tts_cache is not None:
        return _tts_cache
    
    # スレッドセーフな初期化（asyncio + threading混在環境）
    import threading
    if _tts_cache_lock is None:
        _tts_cache_lock = threading.Lock()
    
    with _tts_cache_lock:
        # ダブルチェックロック
        if _tts_cache is not None:
            return _tts_cache
        
        # TorchCodec 依存を排除するため、先に torchaudio をパッチ
        _patch_torchaudio_load()
        
        try:
            from TTS.api import TTS
            import torch
        except Exception as e:
            raise RuntimeError("Coqui TTS の読み込みに失敗しました。requirements を再インストールしてください。") from e
        
        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Coqui TTS モデルを初期化中... (device: {device})")
        print("初回実行時はモデルダウンロードに30-60秒かかります。")
        
        _tts_cache = TTS(model_name="tts_models/multilingual/multi-dataset/xtts_v2").to(device)
        print("Coqui TTS モデル初期化完了")
        
        return _tts_cache


def _parse_slide_index_from_stem(stem: str) -> Optional[int]:
    """ファイル名stemからスライド番号を抽出する（例: slide_000 / slide-12 / slide12）。"""
    m = re.match(r"^slide(?:[_-]?(\d+))$", stem)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _pick_newest(paths: List[str]) -> str:
    """同一indexに複数候補がある場合、mtimeが新しいものを採用する。"""
    if len(paths) == 1:
        return paths[0]
    best = paths[0]
    best_t = -1.0
    for p in paths:
        try:
            t = os.path.getmtime(p)
        except Exception:
            t = -1.0
        if t > best_t:
            best = p
            best_t = t
    return best


def _resolve_audio_path(temp_dir: str, slide_index: int) -> Optional[str]:
    """スライド番号から音声ファイル候補を探して返す。"""
    candidates = [
        os.path.join(temp_dir, f"slide_{slide_index:03d}.mp3"),
        os.path.join(temp_dir, f"slide_{slide_index}.mp3"),
        os.path.join(temp_dir, f"audio_{slide_index:03d}.mp3"),
        os.path.join(temp_dir, f"audio_{slide_index}.mp3"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None

def _get_subtitle_segments(script: str) -> List[dict]:
    """原稿を句読点で分割し、文字数比率でタイミングを計算する（プレビューと同じロジック）"""
    if not script:
        return []
    
    # 句読点で分割（プレビューと同じ正規表現）
    raw_segments = re.split(r'([。、！？!?\n]+)', script)
    raw_segments = [s for s in raw_segments if s.strip()]
    
    # テキストと句読点をマージ
    merged_segments = []
    i = 0
    while i < len(raw_segments):
        text = raw_segments[i]
        punctuation = raw_segments[i + 1] if i + 1 < len(raw_segments) and re.match(r'^[。、！？!?\n]+$', raw_segments[i + 1]) else ""
        if punctuation:
            merged_segments.append(text + punctuation)
            i += 2
        else:
            merged_segments.append(text)
            i += 1
    
    if not merged_segments:
        return []
    
    # 文字数比率でタイミング計算
    total_chars = sum(len(s) for s in merged_segments)
    if total_chars == 0:
        return []
    
    char_count = 0
    segments = []
    for text in merged_segments:
        start_ratio = char_count / total_chars
        char_count += len(text)
        end_ratio = char_count / total_chars
        segments.append({
            'text': text,
            'start_ratio': start_ratio,
            'end_ratio': end_ratio
        })
    
    return segments


def _generate_ass_subtitle(slides_info: List[dict], output_path: str, video_width: int, video_height: int) -> None:
    """ASS形式の字幕ファイルを生成する（プレビューと同じセグメント分割方式）。

    - 文字数比率でタイミングを決める
    - YouTube風の半透明ダーク背景・太字白文字
    - セグメントの長さが0にならないよう最小幅を確保
    """
    # ASS header
    # 環境変数で字幕縦マージンと配置を調整可能にする
    try:
        env_margin_v = int(os.environ.get("SUBTITLE_MARGIN_V", "10"))
    except Exception:
        env_margin_v = 40

    try:
        # ASS の Alignment 値 (1..9)。デフォルトは 2 (bottom-center)
        env_alignment = int(os.environ.get("SUBTITLE_ALIGNMENT", "2"))
        if not (1 <= env_alignment <= 9):
            env_alignment = 2
    except Exception:
        env_alignment = 2

    header = f"""[Script Info]
Title: Slide Voice Maker Subtitles
ScriptType: v4.00+
WrapStyle: 0
PlayResX: {video_width}
PlayResY: {video_height}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
# PrimaryColour: 白, OutlineColour: 黒, BackColour: 半透明グレー
Style: Default,Noto Sans JP,36,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80303030,-1,0,0,0,100,100,0,0,3,2,0,{env_alignment},30,30,{env_margin_v},1


[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    
    def format_time(seconds: float) -> str:
        """秒をASS時刻形式(H:MM:SS.CC)に変換"""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = seconds % 60
        return f"{h}:{m:02d}:{s:05.2f}"
    
    events = []
    current_time = 0.0
    
    min_seg = 0.15  # 秒換算の最小幅（30fpsで約4.5フレーム、字幕切替を確実にする）

    for slide in slides_info:
        script = slide.get('script', '').strip()
        duration = slide.get('duration', 3.0)
        
        if script:
            # プレビューと同じセグメント分割
            segments = _get_subtitle_segments(script)
            
            for seg in segments:
                # 文字数比率からタイミングを計算
                seg_start = current_time + (duration * seg['start_ratio'])
                seg_end = current_time + (duration * seg['end_ratio'])
                if seg_end - seg_start < min_seg:
                    seg_end = seg_start + min_seg
                
                # テキストをASS用にエスケープ
                text = seg['text'].replace('\n', '\\N')
                
                start_str = format_time(seg_start)
                end_str = format_time(seg_end)
                # per-event の MarginV を環境変数で制御して、下寄せの高さを調整できるようにする
                events.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,{env_margin_v},,{text}")
        
        current_time += duration
    
    # BOM付きUTF-8で保存（FFmpeg libassがWindowsで正しく読み込むため）
    with open(output_path, 'w', encoding='utf-8-sig', newline='\n') as f:
        f.write(header)
        f.write('\n'.join(events))
        f.write('\n')


def combine_audio_video(
    output_dir: str,
    resolution: int = 1280,
    output_name: str = "output",
    subtitle: bool = True,
    slides_count: Optional[int] = None,
    temp_subdir: Optional[str] = None,
    output_format: str = "webm",
    script_data_override: Optional[dict[int, str]] = None,
) -> str:
    """output/temp内の音声・画像ファイルから動画を生成する（高速FFmpeg版）
    
    Args:
        output_dir: 出力ディレクトリ
        resolution: 動画の幅（px）
        output_name: 出力ファイル名（拡張子なし）
        subtitle: 字幕を埋め込むかどうか
    
    Returns:
        生成された動画ファイルのパス
    """
    temp_dir = _select_temp_dir(output_dir, output_name=output_name, temp_subdir=temp_subdir)
    if not os.path.exists(temp_dir):
        raise FileNotFoundError(f"temp folder not found: {temp_dir}")
    
    # 画像と音声のペアを収集
    # - 旧ファイル混在対策として、slide_* のみを対象にし、数値でソートする
    # - slides_count が与えられたら 0..slides_count-1 に制限する
    all_files = os.listdir(temp_dir)
    png_files = [f for f in all_files if f.lower().endswith('.png')]
    mp3_files = [f for f in all_files if f.lower().endswith('.mp3')]
    
    by_index: dict[int, List[str]] = {}
    for f in png_files:
        stem = Path(f).stem
        idx = _parse_slide_index_from_stem(stem)
        if idx is None:
            continue
        if slides_count is not None and idx >= int(slides_count):
            continue
        by_index.setdefault(idx, []).append(os.path.join(temp_dir, f))

    if by_index:
        image_indices = sorted(by_index.keys())
        image_paths = [_pick_newest(by_index[i]) for i in image_indices]
        legacy_mode = False
    else:
        # フォールバック（従来互換）: base名で mp3 を探す
        image_files = sorted(png_files)
        audio_files_set = set(mp3_files)
        legacy_mode = True

    if (not legacy_mode and not image_paths) or (legacy_mode and not image_files):
        raise ValueError("No image files found in temp folder")
    
    # 原稿（字幕用）
    # - UIから原稿が送られてきた場合はそれを優先（プレビューと動画字幕の不一致を防ぐ）
    # - 未指定の場合は input/原稿.csv を読む（後方互換）
    script_data: dict[int, str] = {}
    if script_data_override is not None:
        # None でも「指定した」扱いにしてCSVへフォールバックしない
        for k, v in dict(script_data_override).items():
            try:
                idx = int(k)
            except Exception:
                continue
            script_data[idx] = "" if v is None else str(v)
    else:
        script_path = os.path.join(os.path.dirname(output_dir), "input", "原稿.csv")
        if not os.path.exists(script_path):
            script_path = os.path.join(output_dir, "..", "input", "原稿.csv")

        if os.path.exists(script_path):
            try:
                script_data = _read_script_csv(script_path)
            except Exception as e:
                print(f"Warning: Failed to read script CSV: {e}")
    
    slides: List[_SlideItem] = []
    silence_duration = _get_silence_slide_duration()
    
    if not legacy_mode:
        for img_path, slide_index in zip(image_paths, image_indices):
            audio_path = _resolve_audio_path(temp_dir, slide_index)

            # 音声の長さを取得
            duration = silence_duration
            if audio_path and os.path.exists(audio_path):
                try:
                    duration = _get_audio_duration_seconds(audio_path)
                except Exception:
                    pass

            # 音声がない場合は無音MP3を生成
            if not audio_path or not os.path.exists(audio_path):
                audio_path = os.path.join(temp_dir, f"_silence_{slide_index:03d}.mp3")
                _ensure_silence_mp3(audio_path, duration)

            slides.append(
                _SlideItem(
                    page_index=slide_index,
                    image_path=img_path,
                    audio_path=audio_path,
                    script_text=script_data.get(slide_index, ''),
                    duration=duration,
                )
            )
    else:
        for img_file in image_files:
            base = os.path.splitext(img_file)[0]
            audio_file = base + ".mp3"
            img_path = os.path.join(temp_dir, img_file)
            audio_path = os.path.join(temp_dir, audio_file) if audio_file in audio_files_set else None

            # スライドインデックスを抽出 (slide_000 -> 0)
            try:
                slide_index = int(base.split('_')[-1])
            except (ValueError, IndexError):
                slide_index = len(slides)

            # 音声の長さを取得
            duration = silence_duration
            if audio_path and os.path.exists(audio_path):
                try:
                    duration = _get_audio_duration_seconds(audio_path)
                except Exception:
                    pass

            # 音声がない場合は無音MP3を生成
            if not audio_path or not os.path.exists(audio_path):
                audio_path = os.path.join(temp_dir, f"_silence_{slide_index:03d}.mp3")
                _ensure_silence_mp3(audio_path, duration)

            slides.append(
                _SlideItem(
                    page_index=slide_index,
                    image_path=img_path,
                    audio_path=audio_path,
                    script_text=script_data.get(slide_index, ''),
                    duration=duration,
                )
            )
    
    if not slides:
        raise ValueError("No slides to process")
    
    fmt = (output_format or "webm").lower().strip()
    if fmt not in ("webm", "mp4"):
        raise ValueError(f"Unsupported output_format: {output_format}")
    output_path = os.path.join(output_dir, f"{output_name}.{fmt}")
    
    # 高速FFmpegでエンコード
    print(f"Generating video with FFmpeg (high-speed mode)...")
    os.environ["OUTPUT_MAX_WIDTH"] = str(resolution)
    
    # 字幕ファイルを生成
    subtitle_path = None
    if subtitle:
        subtitle_path = os.path.join(temp_dir, f"_subtitles_{output_name}.ass")
        slides_info = [
            {
                'page_index': s.page_index,
                'script': s.script_text,
                'duration': s.duration
            }
            for s in slides
        ]
        # 動画解像度（16:9に揃える）
        video_width = resolution
        video_height = int(round(resolution * 9 / 16))
        _generate_ass_subtitle(slides_info, subtitle_path, video_width, video_height)
        print(f"Generated subtitle file: {subtitle_path}")

    if fmt == "webm":
        _render_webm_with_ffmpeg(slides, output_path, temp_dir, subtitle_path)
    else:
        _render_mp4_with_ffmpeg(slides, output_path, temp_dir, subtitle_path)
    
    print(f"Video generated: {output_path}")
    return output_path


async def process_pdf_and_script(pdf_path, script_path, output_dir):
    """メイン処理"""
    print(f"Processing: {pdf_path}")
    
    # ファイル名の取得（拡張子なし）
    base_name = os.path.splitext(os.path.basename(pdf_path))[0]
    
    # 原稿の読み込み (CSV: index,script) - mojibake-safe
    try:
        script_data = _read_script_csv(script_path)
    except Exception as e:
        print(f"Error reading script CSV ({script_path}): {e}")
        return

    # PDFの読み込み（fitzは遅延import）
    import fitz  # pymupdf
    doc = fitz.open(pdf_path)
    
    temp_dir = os.path.join(output_dir, "temp", base_name)
    os.makedirs(temp_dir, exist_ok=True)

    use_moviepy = os.environ.get("USE_MOVIEPY", "0") == "1"

    slides: List[_SlideItem] = []
    video_clips = []
    final_video = None

    try:
        for i in range(len(doc)):
            print(f"Processing page {i+1}/{len(doc)}")
            page = doc.load_page(i)

            # 画像として保存 (高解像度で)
            image_path = os.path.join(temp_dir, f"slide_{i}.png")
            if not _file_exists_nonempty(image_path):
                scale = _get_render_scale()
                pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
                pix.save(image_path)

            # 原稿の取得
            script_text = script_data.get(i, "")

            # 音声生成
            audio_path = os.path.join(temp_dir, f"audio_{i}.mp3")
            if script_text.strip():
                if not _file_exists_nonempty(audio_path):
                    await generate_voice(script_text, audio_path)
            else:
                # 音声が無い場合でも concat demuxer のため MP3 に揃える
                audio_path = os.path.join(temp_dir, f"silence_{i}.mp3")

            # duration決定（音声があれば音声長、無音なら固定）
            if script_text.strip():
                if os.path.exists(audio_path):
                    duration = _get_audio_duration_seconds(audio_path)
                else:
                    duration = _get_silence_slide_duration()
            else:
                duration = _get_silence_slide_duration()

            if duration <= 0:
                duration = 0.01

            # 無音MP3の場合はduration確定後に生成
            if audio_path.lower().endswith(".mp3") and "silence_" in os.path.basename(audio_path):
                _ensure_silence_mp3(audio_path, duration)

            slides.append(
                _SlideItem(
                    page_index=i,
                    image_path=image_path,
                    audio_path=audio_path,
                    script_text=script_text,
                    duration=duration,
                )
            )

        # 動画出力
        print("Generating video...")
        video_output_path = os.path.join(output_dir, f"{base_name}.webm")

        if not use_moviepy:
            # 高速: FFmpegでconcat（字幕なし）
            _render_webm_with_ffmpeg(slides, video_output_path, temp_dir)
        else:
            # フォールバック: MoviePy（遅い）
            from moviepy.editor import AudioFileClip, ImageClip, concatenate_videoclips

            for slide in slides:
                img_clip = ImageClip(slide.image_path).set_duration(slide.duration)
                if slide.audio_path and os.path.exists(slide.audio_path):
                    audio_clip = AudioFileClip(slide.audio_path)
                    img_clip = img_clip.set_audio(audio_clip)
                video_clips.append(img_clip)

            final_video = concatenate_videoclips(video_clips, method="compose")
            temp_audiofile = os.path.join(temp_dir, f"{base_name}__temp_audio.ogg")
            final_video.write_videofile(
                video_output_path,
                fps=_get_output_fps(),
                codec="libvpx-vp9",
                audio_codec="libvorbis",
                temp_audiofile=temp_audiofile,
                remove_temp=True,
            )

        print("Done!")
    finally:
        try:
            doc.close()
        except Exception:
            pass

        # MoviePyリソース解放
        if final_video is not None:
            try:
                final_video.close()
            except Exception:
                pass

        for c in video_clips:
            try:
                c.close()
            except Exception:
                pass

