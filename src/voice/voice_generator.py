import csv
import io
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import imageio_ffmpeg


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _samples_dir() -> Path:
    return _repo_root() / "src" / "voice" / "models" / "samples"


def _output_dir() -> Path:
    return _repo_root() / "output"


def _patch_torchaudio_load_once() -> None:
    """TorchCodec問題回避: torchaudio.load を soundfile ベースに置き換える。"""
    if getattr(_patch_torchaudio_load_once, "_done", False):
        return
    setattr(_patch_torchaudio_load_once, "_done", True)

    try:
        import torch
        import soundfile as sf
        import torchaudio

        def patched_load(filepath, *args, **kwargs):
            audio_data, sample_rate = sf.read(filepath)
            if audio_data.ndim == 1:
                audio_tensor = torch.from_numpy(audio_data).unsqueeze(0)
            else:
                audio_tensor = torch.from_numpy(audio_data.T)
            return audio_tensor.float(), sample_rate

        torchaudio.load = patched_load
        print("TorchCodecバイパス: torchaudio.load を soundfile ベースにパッチしました")
    except Exception as e:
        print(f"Warning: TorchCodecバイパスに失敗しました: {e}")


def list_speaker_samples(samples_dir: Optional[Path] = None) -> list[Path]:
    base = samples_dir or _samples_dir()
    if not base.exists():
        return []
    wavs = sorted([p for p in base.glob("*.wav") if p.is_file()])
    return wavs


def pick_default_speaker_wav(samples_dir: Optional[Path] = None) -> Optional[Path]:
    """既定の話者WAVを決定する。

    優先順位:
      1) 環境変数 COQUI_SPEAKER_WAV
      2) sample_XX.wav の最大番号
      3) sample.wav
      4) それ以外の *.wav の最新
    """
    env = os.environ.get("COQUI_SPEAKER_WAV")
    if env:
        p = Path(env)
        if p.is_absolute() and p.exists():
            return p
        q = (_repo_root() / env).resolve()
        if q.exists():
            return q

    base = samples_dir or _samples_dir()
    wavs = list_speaker_samples(base)
    if not wavs:
        return None

    numbered: list[tuple[int, Path]] = []
    for p in wavs:
        m = re.match(r"^sample_(\d+)\.wav$", p.name, flags=re.IGNORECASE)
        if m:
            numbered.append((int(m.group(1)), p))
    if numbered:
        return sorted(numbered, key=lambda t: t[0])[-1][1]

    canonical = base / "sample.wav"
    if canonical.exists():
        return canonical

    return sorted(wavs, key=lambda p: p.stat().st_mtime)[-1]


def _decode_csv_bytes(data: bytes) -> str:
    """CSVの文字化け対策デコード。

    優先順位:
      1) UTF-8 (BOM付き含む) を strict で試し、成功したらそれを採用
      2) CP932 を strict で採用

    NOTE:
      CP932 は多くのバイト列を「それっぽく」復号できてしまうため、
      UTF-8のデータでも置換文字(U+FFFD)が出ずに文字化けするケースがある。
      そのため「置換文字率比較」ではなく strict デコードの成否で判定する。
    """
    # BOMがある場合のみUTF-16/32を採用する。
    # UTF-16LE/BE は「どんな偶数長バイト列でも復号できてしまう」ため、
    # BOM無しで試すと誤判定の原因になる。
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig", errors="strict")
    if data.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        return data.decode("utf-32", errors="strict")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="strict")

    # それ以外はヒューリスティックで最も「それっぽい」ものを採用する。
    # CP932は誤判定しやすいので、スコアリングで抑制する。
    candidates = [
        "utf-8-sig",
        "cp932",
        "euc-jp",
    ]

    def japanese_count(s: str) -> int:
        n = 0
        for ch in s:
            o = ord(ch)
            if 0x3040 <= o <= 0x309F:  # Hiragana
                n += 1
            elif 0x30A0 <= o <= 0x30FF:  # Katakana
                n += 1
            elif 0x4E00 <= o <= 0x9FFF:  # CJK Unified Ideographs
                n += 1
        return n

    def score(enc: str) -> tuple[float, str]:
        s = data.decode(enc, errors="replace")
        repl = s.count("\ufffd")
        nul = s.count("\x00")
        jp = japanese_count(s)
        header_bonus = 200.0 if ("index" in s.lower() and "script" in s.lower()) else 0.0
        # replacement / NUL を強く罰し、日本語文字を強く報酬
        val = header_bonus + (jp * 3.0) - (repl * 100.0) - (nul * 50.0)
        return val, s

    best_val = float("-inf")
    best_text = None
    for enc in candidates:
        try:
            val, s = score(enc)
            if val > best_val:
                best_val = val
                best_text = s
        except Exception:
            continue

    if best_text is not None:
        return best_text

    return data.decode("utf-8-sig", errors="replace")


@dataclass(frozen=True)
class ScriptRow:
    index: int
    script: str


def load_script_csv(script_csv_path: Path) -> list[ScriptRow]:
    raw = script_csv_path.read_bytes()
    text = _decode_csv_bytes(raw)

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSVヘッダが読み取れません")

    field_map = {f.strip().lower(): f for f in reader.fieldnames if f}
    if "index" not in field_map or "script" not in field_map:
        raise ValueError("CSVヘッダが不正です（index,script が必要）")

    rows: list[ScriptRow] = []
    for r in reader:
        raw_idx = (r.get(field_map["index"]) or "").strip()
        raw_script = (r.get(field_map["script"]) or "").strip()
        if not raw_idx:
            continue
        try:
            idx = int(raw_idx)
        except Exception:
            continue
        rows.append(ScriptRow(index=idx, script=raw_script))

    rows.sort(key=lambda x: x.index)
    return rows


def _ffmpeg_encode_to_mp3(src_wav: Path, dst_mp3: Path) -> None:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    dst_mp3.parent.mkdir(parents=True, exist_ok=True)

    # 直接 dst_mp3 に書くと、Windows でブラウザ再生中のファイルがロックされて
    # 上書きできないことがあるため、一旦テンポラリに出してから置換する。
    # 拡張子が .mp3 でないと FFmpeg が出力形式を判定できず失敗するため、必ず .tmp.mp3 にする。
    tmp_mp3 = dst_mp3.with_name(dst_mp3.stem + ".tmp" + dst_mp3.suffix)

    args = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostats",
        "-i",
        str(src_wav),
        "-vn",
        "-c:a",
        "libmp3lame",
        "-q:a",
        "3",
        str(tmp_mp3),
    ]

    import subprocess

    proc = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        stderr = proc.stderr or b""
        msg = stderr.decode("utf-8", errors="replace")
        try:
            if tmp_mp3.exists():
                tmp_mp3.unlink(missing_ok=True)
        except Exception:
            pass
        raise RuntimeError(f"FFmpeg MP3 encode failed (code={proc.returncode}): {msg}")

    # 置換（リトライ付き）
    last: Exception | None = None
    for _ in range(6):
        try:
            os.replace(str(tmp_mp3), str(dst_mp3))
            return
        except PermissionError as e:
            last = e
            # 既存がロックされている場合、少し待つ
            import time

            time.sleep(0.25)
        except Exception as e:
            last = e
            break

    # 最後の手段: 既存を退避してから置換を試す
    try:
        if dst_mp3.exists():
            bak = dst_mp3.with_name(dst_mp3.stem + ".bak" + dst_mp3.suffix)
            try:
                if bak.exists():
                    bak.unlink(missing_ok=True)
            except Exception:
                pass
            os.replace(str(dst_mp3), str(bak))
        os.replace(str(tmp_mp3), str(dst_mp3))
        return
    except Exception as e:
        last = last or e
        # tmp を残さない
        try:
            if tmp_mp3.exists():
                tmp_mp3.unlink(missing_ok=True)
        except Exception:
            pass
        raise RuntimeError(f"MP3の上書きに失敗しました（ファイルが使用中の可能性）: {dst_mp3}") from last


class VoiceGenerator:
    """XTTS v2 を用いた音声生成。

    - input/原稿.csv を読み込み（文字化け対策あり）、output/slide_000.mp3 等へ保存する。
    - speaker_wav は src/voice/models/samples/*.wav から自動選択（上書き禁止の運用に対応）。
    """

    def __init__(self):
        # テスト/CI向け: 重いモデルロードを避けるためのフェイク実装
        # - 1: 無音WAVを生成してMP3化する（speaker_wav は実質未使用）
        self._fake_tts = os.environ.get("SVM_FAKE_TTS", "0") == "1"

        self._tts = None
        if not self._fake_tts:
            _patch_torchaudio_load_once()
            import torch

            device = "cuda" if torch.cuda.is_available() else "cpu"
            from TTS.api import TTS  # 重いので遅延import

            self._tts = TTS(model_name="tts_models/multilingual/multi-dataset/xtts_v2").to(device)

    def generate_one(
        self,
        *,
        index: int,
        script: str,
        speaker_wav: Path,
        output_dir: Optional[Path] = None,
        overwrite: bool = True,
    ) -> Path:
        out_dir = output_dir or _output_dir()
        out_dir.mkdir(parents=True, exist_ok=True)

        mp3_path = out_dir / f"slide_{index:03d}.mp3"
        if mp3_path.exists() and not overwrite:
            raise FileExistsError(f"既存ファイルの上書きは禁止されています: {mp3_path}")

        temp_dir = out_dir / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        wav_path = temp_dir / f"slide_{index:03d}.wav"

        if self._fake_tts:
            # script長に応じて最短0.4秒〜最長8秒の無音を生成
            import numpy as np
            import soundfile as sf

            sr = 24000
            seconds = min(8.0, max(0.4, 0.06 * len(script)))
            samples = int(sr * seconds)
            audio = np.zeros((samples,), dtype=np.float32)
            sf.write(str(wav_path), audio, sr)
        else:
            if self._tts is None:
                raise RuntimeError("TTSモデルが初期化されていません")

            # XTTS は WAV 生成が安定しやすいので一旦 WAV → MP3
            self._tts.tts_to_file(
                text=script,
                speaker_wav=str(speaker_wav),
                language="ja",
                file_path=str(wav_path),
            )

        _ffmpeg_encode_to_mp3(wav_path, mp3_path)
        return mp3_path

    def generate_from_csv(
        self,
        *,
        script_csv_path: Path,
        speaker_wav: Path,
        output_dir: Optional[Path] = None,
        overwrite: bool = True,
    ) -> list[Path]:
        rows = load_script_csv(script_csv_path)
        if not rows:
            raise ValueError("有効な原稿データが見つかりません")

        generated: list[Path] = []
        for r in rows:
            if not r.script.strip():
                continue
            generated.append(
                self.generate_one(
                    index=r.index,
                    script=r.script,
                    speaker_wav=speaker_wav,
                    output_dir=output_dir,
                    overwrite=overwrite,
                )
            )
        return generated


_VOICE_LOCK = threading.Lock()
_VOICE_INSTANCE: Optional[VoiceGenerator] = None


def get_voice_generator() -> VoiceGenerator:
    global _VOICE_INSTANCE
    with _VOICE_LOCK:
        if _VOICE_INSTANCE is None:
            print("音声モデルを初期化中...")
            _VOICE_INSTANCE = VoiceGenerator()
            print("初期化完了")
        return _VOICE_INSTANCE


if __name__ == "__main__":
    repo_root = _repo_root()
    script_csv = repo_root / "input" / "原稿.csv"
    speaker = pick_default_speaker_wav()
    if not speaker:
        raise SystemExit("話者サンプルが見つかりません。src/voice/models/samples に sample_01.wav 等を配置してください。")

    vg = get_voice_generator()
    out = vg.generate_from_csv(script_csv_path=script_csv, speaker_wav=speaker, output_dir=repo_root / "output")
    print(f"生成完了: {len(out)} 件")
