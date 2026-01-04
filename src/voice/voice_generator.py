import csv
import io
import json
import os
import re
import threading
import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import imageio_ffmpeg

from src.logger import setup_logger

logger = setup_logger("VoiceGenerator")


_INIT_STATE_LOCK = threading.Lock()
_INIT_STATE: dict[str, object] = {
    "ready": False,
    "stage": "not_started",
    "message": "",
    "started_at": None,
    "updated_at": None,
    "error": None,
}


def _set_init_state(stage: str, *, message: str = "", error: str | None = None, ready: bool | None = None) -> None:
    """モデル初期化の進捗を共有状態として更新する（UI/診断向け）。"""

    with _INIT_STATE_LOCK:
        _INIT_STATE["stage"] = stage
        if message:
            _INIT_STATE["message"] = message
        if ready is not None:
            _INIT_STATE["ready"] = bool(ready)
        if _INIT_STATE.get("started_at") is None:
            _INIT_STATE["started_at"] = time.time()
        _INIT_STATE["updated_at"] = time.time()
        if error is not None:
            _INIT_STATE["error"] = error


def get_tts_init_state() -> dict[str, object]:
    """初期化進捗を返す（FastAPIがJSON化できる素朴なdict）。"""

    with _INIT_STATE_LOCK:
        return dict(_INIT_STATE)



def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _samples_dir() -> Path:
    return _repo_root() / "src" / "voice" / "models" / "samples"


def _output_dir() -> Path:
    return _repo_root() / "output"


def _voices_dir() -> Path:
    """アプリ側で管理する voice キャッシュ保存先。"""
    return _repo_root() / "src" / "voice" / "models" / "voices"


def _voice_model_json_path() -> Path:
    return _repo_root() / "src" / "voice" / "models" / "tts_model.json"


def _load_voice_file(voice_file: Path, *, map_location: str | object):
    """PyTorch 2.6+ でデフォルトになった ``weights_only=True`` を避けて読み込む。

    XTTS の話者キャッシュ(.pth)はピクルを含むため、weights_only=True だと
    UnpicklingError になり、せっかくのキャッシュを使えずに毎回再計算される。
    ここでは明示的に ``weights_only=False`` を指定し、古いtorchでも動くよう
    TypeError をフォールバックで吸収する。
    """

    import torch

    load_kwargs = {"map_location": map_location}

    try:
        return torch.load(str(voice_file), weights_only=False, **load_kwargs)
    except TypeError:
        # torch<2.6 は weights_only 引数を持たない
        return torch.load(str(voice_file), **load_kwargs)


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
        logger.info("TorchCodecバイパス: torchaudio.load を soundfile ベースにパッチしました")
    except Exception as e:
        logger.warning(f"Warning: TorchCodecバイパスに失敗しました: {e}")


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

    - input/原稿.csv を読み込み（文字化け対策あり）、output/voice_000.mp3 等へ保存する。
    - speaker_wav は src/voice/models/samples/*.wav から自動選択（上書き禁止の運用に対応）。
    """

    def __init__(self):
        t_init0 = time.perf_counter()
        _set_init_state("init_start", message="VoiceGenerator init start")
        # テスト/CI向け: 重いモデルロードを避けるためのフェイク実装
        # - 1: 無音WAVを生成してMP3化する（speaker_wav は実質未使用）
        self._fake_tts = os.environ.get("SVM_FAKE_TTS", "0") == "1"

        self._tts = None
        if not self._fake_tts:
            logger.info("[VoiceGenerator] init: start real TTS (XTTS v2)")
            try:
                t0 = time.perf_counter()
                _set_init_state("torchaudio_patch", message="patch torchaudio.load")
                _patch_torchaudio_load_once()
                logger.info(f"[VoiceGenerator] init: torchaudio patch done in {(time.perf_counter() - t0):.3f}s")

                t1 = time.perf_counter()
                _set_init_state("import_torch", message="import torch")
                import torch

                device = "cuda" if torch.cuda.is_available() else "cpu"
                self._device = device
                logger.info(
                    f"[VoiceGenerator] init: torch ready in {(time.perf_counter() - t1):.3f}s (device={device})"
                )

                t2 = time.perf_counter()
                _set_init_state("import_tts_api", message="import TTS.api")
                from TTS.api import TTS  # 重いので遅延import

                logger.info(f"[VoiceGenerator] init: imported TTS.api in {(time.perf_counter() - t2):.3f}s")

                # ここが最も時間がかかる: モデルのDL/ロード
                t3 = time.perf_counter()
                _set_init_state("load_xtts_model", message="loading XTTS model")
                logger.info("[VoiceGenerator] init: loading XTTS model... (this can take several minutes on first run)")
                self._tts = TTS(model_name="tts_models/multilingual/multi-dataset/xtts_v2").to(device)
                logger.info(f"[VoiceGenerator] init: XTTS model ready in {(time.perf_counter() - t3):.3f}s")
            except Exception:
                _set_init_state("init_error", message="XTTS init failed", error="exception", ready=False)
                logger.exception("[VoiceGenerator] init: failed to initialize XTTS model")
                raise
        else:
            self._device = "cpu"
            logger.info("[VoiceGenerator] init: fake TTS mode enabled (SVM_FAKE_TTS=1)")
            _set_init_state("fake_tts", message="fake TTS mode", ready=True)

        # voice キャッシュ（.pth）から読み込んだ latent をメモリに保持して再利用する
        # これにより、生成ごとに .pth を読む/latent を計算する経路を避ける。
        self._voice_latents: dict[str, dict[str, object]] = {}

        # サーバー再起動後でも、既に構築済みの voice キャッシュがあれば自動で読み込む
        if not self._fake_tts:
            try:
                default_voice_id = "myvoice"
                default_voice_file = _voices_dir() / f"{default_voice_id}.pth"
                if default_voice_file.exists():
                    ok = self.load_voice_cache(voice_id=default_voice_id, voice_dir=default_voice_file.parent)
                    logger.info(f"[VoiceGenerator] voice cache auto-load: {default_voice_file} ok={ok}")
            except Exception as e:
                logger.warning(f"[VoiceGenerator] voice cache auto-load skipped: {e}")

            # アプリが保存した tts_model.json の設定（voice_id/voice_dir）があればそれも優先して読み込む。
            # ※ UIで「音声生成モデル構築」を押した後のサーバー再起動でも、埋め込みキャッシュを確実に使うため。
            try:
                p = _voice_model_json_path()
                if p.exists():
                    data = json.loads(p.read_text(encoding="utf-8"))
                    if isinstance(data, dict) and data.get("voice_id") and data.get("voice_dir"):
                        vid = str(data.get("voice_id"))
                        vdir_raw = str(data.get("voice_dir"))
                        vdir = Path(vdir_raw)
                        vdir = vdir if vdir.is_absolute() else (_repo_root() / vdir).resolve()
                        vf = vdir / f"{vid}.pth"
                        if vf.exists():
                            ok = self.load_voice_cache(voice_id=vid, voice_dir=vdir)
                            logger.info(f"[VoiceGenerator] voice cache auto-load (tts_model.json): {vf} ok={ok}")
            except Exception as e:
                logger.warning(f"[VoiceGenerator] voice cache auto-load (tts_model.json) skipped: {e}")

        logger.info(f"[VoiceGenerator] init: done in {(time.perf_counter() - t_init0):.3f}s")
        if not self._fake_tts:
            _set_init_state("ready", message="XTTS ready", ready=True)

    def load_voice_cache(
        self,
        *,
        voice_id: str = "myvoice",
        voice_dir: Optional[Path] = None,
    ) -> bool:
        """voice キャッシュ(.pth)を読み込んで、生成時にメモリ再利用できる状態にする。"""

        if self._fake_tts:
            # フェイク実装では latent は使わないため、存在確認だけでOK
            return True

        if self._tts is None or self._tts.synthesizer is None or self._tts.synthesizer.tts_model is None:
            raise RuntimeError("TTSモデルが初期化されていません")

        out_dir = (voice_dir or _voices_dir()).resolve()
        voice_file = out_dir / f"{voice_id}.pth"
        if not voice_file.exists() or voice_file.stat().st_size == 0:
            return False

        try:
            data = _load_voice_file(voice_file, map_location=self._device)
        except Exception as e:
            logger.error(f"[VoiceGenerator] voice cache load failed ({voice_file}): {e}")
            return False

        # Coqui TTS/XTTS のバージョン差分で、.pth の構造が「トップレベルdict」と限らないことがある。
        # そのため、キーを“再帰的”に探索して latent を抽出する。
        gpt_candidates = (
            "gpt_conditioning_latents",
            "gpt_cond_latents",
            "gpt_cond_latent",
            "gpt_latent",
            "gpt_cond_latent_avg",
            "gpt_cond_latents_avg",
        )
        spk_candidates = (
            "speaker_embedding",
            "spk_embedding",
            "speaker_emb",
            "embedding",
            "speaker_embedding_avg",
        )

        def _deep_find(obj: object, keys: tuple[str, ...], *, max_depth: int = 6) -> tuple[Optional[object], Optional[str]]:
            if max_depth < 0:
                return None, None
            if isinstance(obj, dict):
                for k in keys:
                    if k in obj:
                        return obj[k], k
                for v in obj.values():
                    found, key = _deep_find(v, keys, max_depth=max_depth - 1)
                    if found is not None:
                        return found, key
            elif isinstance(obj, (list, tuple)):
                for v in obj:
                    found, key = _deep_find(v, keys, max_depth=max_depth - 1)
                    if found is not None:
                        return found, key
            return None, None

        gpt_val, gpt_key = _deep_find(data, gpt_candidates)
        spk_val, spk_key = _deep_find(data, spk_candidates)
        if gpt_val is None or spk_val is None:
            return False

        # 互換: list/tuple で 1要素だけ包まれている場合は剥がす
        if isinstance(gpt_val, (list, tuple)) and len(gpt_val) == 1:
            gpt_val = gpt_val[0]
        if isinstance(spk_val, (list, tuple)) and len(spk_val) == 1:
            spk_val = spk_val[0]

        self._voice_latents[voice_id] = {
            "gpt": gpt_val,
            "spk": spk_val,
            "source": str(voice_file),
            "gpt_key": gpt_key or "",
            "spk_key": spk_key or "",
        }
        return True

    def _try_generate_wav_with_latents(self, *, voice_id: str, script: str, wav_path: Path) -> bool:
        """XTTSの latent を直接渡して WAV を生成する（対応していない環境では False）。"""

        if self._fake_tts:
            return False
        if self._tts is None or self._tts.synthesizer is None or self._tts.synthesizer.tts_model is None:
            return False

        lat = self._voice_latents.get(voice_id)
        if not lat:
            return False

        tts_model = self._tts.synthesizer.tts_model
        if not hasattr(tts_model, "inference"):
            return False

        gpt = lat.get("gpt")
        spk = lat.get("spk")
        if gpt is None or spk is None:
            return False

        # inference はモデルと同じ device 上の Tensor を期待する（特に CUDA 時）
        try:
            import torch

            target_device = None
            try:
                # nn.Module 由来なら parameters() から device を取得できる
                target_device = next(tts_model.parameters()).device  # type: ignore[attr-defined]
            except Exception:
                # fallback
                target_device = torch.device(self._device)

            if isinstance(gpt, torch.Tensor) and gpt.device != target_device:
                gpt = gpt.to(target_device)
            if isinstance(spk, torch.Tensor) and spk.device != target_device:
                spk = spk.to(target_device)
        except Exception:
            # device 整合に失敗しても、後段で動く可能性があるため続行
            pass

        # 返却値/引数はバージョン差分があるため、signature を見て適応する
        out = None
        try:
            import inspect

            sig = inspect.signature(tts_model.inference)
            params = sig.parameters

            kwargs: dict[str, object] = {}

            if "text" in params:
                kwargs["text"] = script
            if "language" in params:
                kwargs["language"] = "ja"
            if "lang" in params and "language" not in params:
                kwargs["lang"] = "ja"

            # gpt latent
            for name in ("gpt_cond_latent", "gpt_conditioning_latents", "gpt_cond_latents", "gpt_latent"):
                if name in params:
                    kwargs[name] = gpt
                    break

            # speaker embedding
            for name in ("speaker_embedding", "spk_embedding", "speaker_emb", "embedding"):
                if name in params:
                    kwargs[name] = spk
                    break

            if "enable_text_splitting" in params:
                kwargs["enable_text_splitting"] = True

            if "text" in kwargs:
                out = tts_model.inference(**kwargs)
            else:
                # どうしても text 引数名が見つからない場合は positional で試す
                out = tts_model.inference(script, "ja", gpt, spk)
        except Exception:
            return False

        if out is None:
            return False

        # out から波形とサンプルレートを抽出
        wav = None
        sr = 24000
        try:
            if isinstance(out, dict):
                wav = out.get("wav") or out.get("audio")
                sr = int(out.get("sample_rate") or out.get("sr") or sr)
            elif isinstance(out, tuple) and len(out) >= 1:
                wav = out[0]
                if len(out) >= 2:
                    try:
                        sr = int(out[1])
                    except Exception:
                        pass
            else:
                wav = out
        except Exception:
            return False

        if wav is None:
            return False

        import numpy as np
        import soundfile as sf

        try:
            import torch

            if isinstance(wav, torch.Tensor):
                wav = wav.detach().cpu().float().numpy()
        except Exception:
            pass

        wav = np.asarray(wav, dtype=np.float32)
        if wav.ndim > 1:
            # 念のため mono 化
            wav = wav.reshape(-1)

        sf.write(str(wav_path), wav, sr)
        return True

    def build_voice_cache(
        self,
        *,
        speaker_wav: Path,
        voice_id: str = "myvoice",
        voice_dir: Optional[Path] = None,
    ) -> Path:
        """話者埋め込み（XTTS v2 の conditioning latents 等）を事前計算して保存する。

        XTTS v2 は `speaker_wav` から毎回 latent を計算するが、Coqui TTS の
        `clone_voice()` で `voice_dir/<voice_id>.pth` にキャッシュとして保存できる。
        生成時は `speaker=<voice_id>` + `voice_dir=...` + `speaker_wav=None` として
        読み込ませる。
        """

        if not speaker_wav.exists():
            raise FileNotFoundError(f"speaker_wav が見つかりません: {speaker_wav}")

        out_dir = (voice_dir or _voices_dir()).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        voice_file = out_dir / f"{voice_id}.pth"

        if self._fake_tts:
            # テスト/CI向け: 実TTSが無い場合でも「保存された」状態だけ作る。
            # 生成時は speaker_wav を使わずこの値も参照しないため、内容は最小でよい。
            voice_file.write_bytes(b"SVM_FAKE_VOICE")
            return voice_file

        if self._tts is None or self._tts.synthesizer is None or self._tts.synthesizer.tts_model is None:
            raise RuntimeError("TTSモデルが初期化されていません")

        # Coqui TTS の CloningMixin により `<voice_dir>/<speaker_id>.pth` が保存される。
        # XTTS v2 の `_clone_voice()` が `gpt_conditioning_latents` と `speaker_embedding` を生成する。
        tts_model = self._tts.synthesizer.tts_model
        tts_model.clone_voice(
            speaker_wav=str(speaker_wav),
            speaker_id=voice_id,
            voice_dir=str(out_dir),
        )

        if not voice_file.exists() or voice_file.stat().st_size == 0:
            raise RuntimeError(f"voice キャッシュ保存に失敗しました: {voice_file}")

        # 生成時の再計算を避けるため、保存した .pth を即ロードしてメモリに保持する
        try:
            self.load_voice_cache(voice_id=voice_id, voice_dir=out_dir)
        except Exception as e:
            logger.warning(f"[VoiceGenerator] voice cache load failed (non-fatal): {e}")
        return voice_file

    def generate_one(
        self,
        *,
        index: int,
        script: str,
        speaker_wav: Optional[Path] = None,
        voice_id: Optional[str] = None,
        voice_dir: Optional[Path] = None,
        output_dir: Optional[Path] = None,
        overwrite: bool = True,
    ) -> Path:
        out_dir = output_dir or _output_dir()
        out_dir.mkdir(parents=True, exist_ok=True)

        mp3_path = out_dir / f"voice_{index:03d}.mp3"
        if mp3_path.exists() and not overwrite:
            raise FileExistsError(f"既存ファイルの上書きは禁止されています: {mp3_path}")

        temp_dir = out_dir / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        wav_path = temp_dir / f"voice_{index:03d}.wav"

        logger.info(
            f"[VoiceGenerator] start index={index} wav={wav_path.name} mp3={mp3_path.name} "
            f"speaker_wav={speaker_wav} voice_id={voice_id} voice_dir={voice_dir}"
        )

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
            logger.info(f"[VoiceGenerator] Generating WAV... script_len={len(script)}")
            t0 = time.perf_counter()
            if voice_id and voice_dir:
                # 事前構築済み voice キャッシュを優先利用
                # 1) 可能なら .pth を明示ロードして latent をメモリ再利用
                if voice_id not in self._voice_latents:
                    try:
                        self.load_voice_cache(voice_id=voice_id, voice_dir=Path(voice_dir).resolve())
                    except Exception as e:
                        logger.warning(f"[VoiceGenerator] load_voice_cache failed: {e}")

                # 2) 対応していれば latent を直接渡す経路（最速）
                used_latents = False
                try:
                    used_latents = self._try_generate_wav_with_latents(voice_id=voice_id, script=script, wav_path=wav_path)
                except Exception as e:
                    used_latents = False
                    logger.error(f"[VoiceGenerator] latent inference failed, fallback: {e}")

                if used_latents:
                    logger.info(f"[VoiceGenerator] Using in-memory voice latents: voice_id={voice_id}")
                else:
                    # 3) フォールバック: Coqui TTS 側の speaker/voice_dir 経路（.pthを内部で読む）
                    logger.info(f"[VoiceGenerator] Fallback to tts_to_file (re-loading pth internally)")
                    self._tts.tts_to_file(
                        text=script,
                        speaker=voice_id,
                        speaker_wav=None,
                        language="ja",
                        file_path=str(wav_path),
                        voice_dir=str(Path(voice_dir).resolve()),
                    )
            else:
                if speaker_wav is None:
                    raise ValueError("speaker_wav または (voice_id, voice_dir) のどちらかが必要です")
                self._tts.tts_to_file(
                    text=script,
                    speaker_wav=str(speaker_wav),
                    language="ja",
                    file_path=str(wav_path),
                )
            t1 = time.perf_counter()
            
            if not wav_path.exists() or wav_path.stat().st_size == 0:
                raise RuntimeError(f"WAV生成に失敗しました（ファイルが存在しないか空です）: {wav_path}")
            logger.info(f"[VoiceGenerator] WAV generated: {wav_path} (size={wav_path.stat().st_size} bytes)")
            logger.info(f"[VoiceGenerator] WAV generation time: {(t1 - t0):.3f}s")

        t2 = time.perf_counter()
        _ffmpeg_encode_to_mp3(wav_path, mp3_path)
        t3 = time.perf_counter()
        if not mp3_path.exists() or mp3_path.stat().st_size == 0:
             raise RuntimeError(f"MP3変換に失敗しました（ファイルが存在しないか空です）: {mp3_path}")

        logger.info(f"[VoiceGenerator] MP3 encode time: {(t3 - t2):.3f}s")
        logger.info(f"[VoiceGenerator] done index={index} -> {mp3_path} (size={mp3_path.stat().st_size} bytes)")
        return mp3_path

    def generate_from_csv(
        self,
        *,
        script_csv_path: Path,
        speaker_wav: Optional[Path] = None,
        voice_id: Optional[str] = None,
        voice_dir: Optional[Path] = None,
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
                    voice_id=voice_id,
                    voice_dir=voice_dir,
                    output_dir=output_dir,
                    overwrite=overwrite,
                )
            )
        return generated


_VOICE_LOCK = threading.Lock()
_VOICE_INSTANCE: Optional[VoiceGenerator] = None
_VG_FUTURE: Optional[asyncio.Future[VoiceGenerator]] = None


def get_voice_generator() -> VoiceGenerator:
    global _VOICE_INSTANCE
    with _VOICE_LOCK:
        if _VOICE_INSTANCE is None:
            logger.info("音声モデルを初期化中...")
            _VOICE_INSTANCE = VoiceGenerator()
            logger.info("初期化完了")
        return _VOICE_INSTANCE


async def get_voice_generator_async() -> VoiceGenerator:
    """非同期コンテキストで VoiceGenerator を1回だけ初期化する。

    - 初回のみスレッドプールでモデルロードを実行し、イベントループのブロックを避ける。
    - 2回目以降は同じ Future を await するだけなので即時復帰する。
    """

    global _VG_FUTURE
    if _VG_FUTURE is None:
        loop = asyncio.get_running_loop()
        _VG_FUTURE = loop.run_in_executor(None, get_voice_generator)
    return await _VG_FUTURE


if __name__ == "__main__":
    repo_root = _repo_root()
    script_csv = repo_root / "input" / "原稿.csv"
    speaker = pick_default_speaker_wav()
    if not speaker:
        raise SystemExit("話者サンプルが見つかりません。src/voice/models/samples に sample_01.wav 等を配置してください。")

    vg = get_voice_generator()
    out = vg.generate_from_csv(script_csv_path=script_csv, speaker_wav=speaker, output_dir=repo_root / "output")
    print(f"生成完了: {len(out)} 件")
