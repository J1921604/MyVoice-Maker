import os
import re
import sys
import asyncio
import subprocess
import shutil
import time
import threading
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import imageio_ffmpeg

# srcフォルダをパスに追加（相対インポート対応）
sys.path.insert(0, str(Path(__file__).parent))

from voice.voice_generator import (
    ScriptRow,
    get_voice_generator,
    load_script_csv,
    pick_default_speaker_wav,
)


_CSV_LOCK = threading.Lock()
_LAST_UPLOADED_SCRIPT_CSV: Optional[Path] = None


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _input_dir(repo_root: Path) -> Path:
    # テスト容易性のため、入出力ディレクトリは環境変数で差し替え可能にする
    return Path(os.environ.get("SVM_INPUT_DIR", str(repo_root / "input"))).resolve()


def _output_dir(repo_root: Path) -> Path:
    return Path(os.environ.get("SVM_OUTPUT_DIR", str(repo_root / "output"))).resolve()


RESOLUTION_MAP: dict[str, int] = {
    "720": 1280,
    "720p": 1280,
    "1080": 1920,
    "1080p": 1920,
    "1440": 2560,
    "1440p": 2560,
}


app = FastAPI(title="MyVoice Maker Local API")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/warmup_tts")
async def warmup_tts() -> dict[str, str]:
    """Coqui TTSモデルを事前ロードする（初回アクセス高速化）"""
    try:
        # 初回のモデルロードは重く、イベントループをブロックすると他のAPIが固まるため
        # スレッドに逃がして並行リクエストに耐える。
        await asyncio.to_thread(get_voice_generator)
        return {"status": "ready", "message": "Coqui TTS model loaded successfully"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _ffmpeg_convert_to_wav(src_path: Path, dst_path: Path) -> None:
    """任意の音声を PCM 16-bit mono WAV に変換する（XTTS v2向け）。"""
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    dst_path.parent.mkdir(parents=True, exist_ok=True)

    # XTTS は入力のサンプルレートに厳密ではないが、安定のため 24kHz に揃える。
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
        stderr = proc.stderr or b""
        try:
            msg = stderr.decode("utf-8")
        except Exception:
            msg = stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"FFmpeg conversion failed (code={proc.returncode}): {msg}")


def _sanitize_filename(name: str) -> str:
    # すごく雑に危険文字だけ落とす（Windows/Unix両方を意識）
    name = name.strip().replace("\\", "_").replace("/", "_")
    name = re.sub(r"[\x00-\x1f<>:\"|?*]", "_", name)
    if not name:
        raise HTTPException(status_code=400, detail="ファイル名が不正です")
    return name


def clear_temp_folder(temp_dir: str) -> bool:
    """一時フォルダを削除して作り直す。

    Windowsのファイルロックを考慮し、軽いリトライを行う。
    """
    p = Path(temp_dir)
    try:
        if p.exists():
            last_perm: PermissionError | None = None
            for _ in range(3):
                try:
                    shutil.rmtree(p, ignore_errors=False)
                    break
                except PermissionError as e:
                    last_perm = e
                    time.sleep(0.3)

            # どうしても消せない（ロックされ続ける）場合は、フォルダ名を退避して新規作成する。
            # これにより「古いtempが残って混線する」問題を回避できる。
            if p.exists():
                ts = time.strftime("%Y%m%d-%H%M%S")
                parked = p.with_name(p.name + f"_locked_{ts}")
                try:
                    p.rename(parked)
                except Exception:
                    # rename も失敗する場合は諦める（後続で mkdir は試す）
                    if last_perm:
                        raise last_perm
        p.mkdir(parents=True, exist_ok=True)
        return True
    except Exception:
        # 最後の手段としてフォルダを残しつつ続行
        try:
            p.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return False


@app.post("/api/upload/pdf")
async def upload_pdf(file: UploadFile = File(...)) -> dict[str, str]:
    raise HTTPException(status_code=410, detail="このアプリは音声生成専用です（PDF/動画機能は削除されました）")


@app.post("/api/upload/csv")
async def upload_csv(file: UploadFile = File(...)) -> dict[str, object]:
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="CSVファイルを指定してください")

    repo_root = _repo_root()
    in_dir = _input_dir(repo_root)
    in_dir.mkdir(parents=True, exist_ok=True)

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="CSVが空です")

    # Windowsで input/原稿.csv がExcel等でロックされると write_bytes が PermissionError になり、
    # そのままだと 500 で落ちる。必ずユニーク名に保存し、可能なら原稿.csvへも反映する。
    global _LAST_UPLOADED_SCRIPT_CSV

    ts = time.strftime("%Y%m%d-%H%M%S")
    unique = in_dir / f"原稿_{ts}.csv"

    def try_write(p: Path, payload: bytes) -> None:
        last: Exception | None = None
        for _ in range(3):
            try:
                p.write_bytes(payload)
                return
            except PermissionError as e:
                last = e
                time.sleep(0.25)
        if last:
            raise last

    try:
        with _CSV_LOCK:
            try_write(unique, data)
            _LAST_UPLOADED_SCRIPT_CSV = unique
    except PermissionError as e:
        raise HTTPException(status_code=423, detail=f"CSVを保存できません（他アプリで開いていませんか？）: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"CSV保存に失敗しました: {e}")

    # サーバー側で文字化け対処 + CSVパースし、UIへそのまま返す。
    try:
        rows = load_script_csv(unique)
        slides = [{"index": r.index, "script": r.script} for r in rows]
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"CSVの解析に失敗しました: {e}")

    canonical = in_dir / "原稿.csv"
    canonical_saved = False
    try:
        # 可能なら canonical を更新（失敗しても UI には成功を返す）
        # ロックされている場合はスキップし、generate_from_csv は最後にアップロードされたCSVを優先する。
        try_write(canonical, data)
        canonical_saved = True
    except Exception:
        canonical_saved = False

    return {
        "saved": str(unique),
        "filename": unique.name,
        "canonical_saved": canonical_saved,
        "canonical_path": str(canonical),
        "slides": slides,
    }


@app.post("/api/upload/recording")
async def upload_recording(file: UploadFile = File(...)) -> dict[str, str]:
    """録音ファイルをsrc/voice/models/samples/に保存（上書き禁止: sample_01.wav などで保存）。"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="ファイル名が指定されていません")

    repo_root = _repo_root()
    samples_dir = repo_root / "src" / "voice" / "models" / "samples"
    samples_dir.mkdir(parents=True, exist_ok=True)

    # アップロードされたファイルを一旦そのまま保存（拡張子・MIMEは信用しない）
    raw_filename = _sanitize_filename(Path(file.filename).name)
    raw_ext = Path(raw_filename).suffix.lower()
    if raw_ext not in (".wav", ".webm", ".ogg", ".mp3", ".m4a", ".aac", ".flac"):
        # ブラウザ録音は webm が多い。未知拡張子は .webm として扱う
        raw_filename = str(Path(raw_filename).with_suffix(".webm"))

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="ファイルが空です")

    # 変換前の退避
    uploaded_dir = samples_dir / "uploaded"
    uploaded_dir.mkdir(parents=True, exist_ok=True)
    raw_path = uploaded_dir / raw_filename
    raw_path.write_bytes(data)

    # 上書き禁止のため sample_01.wav, sample_02.wav... として保存する
    existing = sorted(samples_dir.glob("sample_*.wav"))
    max_n = 0
    for p in existing:
        m = re.match(r"^sample_(\d+)\.wav$", p.name, flags=re.IGNORECASE)
        if m:
            max_n = max(max_n, int(m.group(1)))
    dst_wav = samples_dir / f"sample_{max_n + 1:02d}.wav"
    try:
        await asyncio.to_thread(_ffmpeg_convert_to_wav, raw_path, dst_wav)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"録音のWAV変換に失敗しました: {e}")

    return {"saved": str(dst_wav), "filename": dst_wav.name}


class GenerateAudioRequest(BaseModel):
    slide_index: int
    script: str
    overwrite: bool = True


class GenerateFromCsvRequest(BaseModel):
    overwrite: bool = True
    speaker_wav: Optional[str] = None  # 指定があればそれを優先（相対パスはリポジトリルート基準）


class ClearTempRequest(BaseModel):
    # 音声生成で使う一時ファイル（wav等）を消す。基本は output/temp を全削除。
    scope: Optional[str] = None


@app.post("/api/generate_audio")
async def generate_audio(req: GenerateAudioRequest) -> dict[str, str]:
    """単一スライドの音声を output/slide_000.mp3 等へ保存する。"""
    repo_root = _repo_root()
    out_dir = _output_dir(repo_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not req.script or not req.script.strip():
        return {"audio_url": "", "path": ""}

    speaker = pick_default_speaker_wav()
    if not speaker:
        raise HTTPException(status_code=400, detail="話者サンプルが見つかりません。録音して sample_01.wav 等を作成してください")

    try:
        vg = get_voice_generator()
        audio_path = await asyncio.to_thread(
            vg.generate_one,
            index=req.slide_index,
            script=req.script,
            speaker_wav=speaker,
            output_dir=out_dir,
            overwrite=req.overwrite,
        )
        audio_url = ""
        try:
            rel = Path(audio_path).relative_to(repo_root)
            audio_url = f"/{rel.as_posix()}"
        except Exception:
            # 出力先が repo 外（SVM_OUTPUT_DIR差し替え等）の場合、static配信できないためURLは空
            audio_url = ""
        return {"audio_url": audio_url, "path": str(audio_path)}
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"音声生成エラー: {e}")


@app.post("/api/generate_from_csv")
async def generate_from_csv(req: GenerateFromCsvRequest) -> dict[str, object]:
    """input/原稿.csv から音声を一括生成して output/ に保存する。"""
    repo_root = _repo_root()
    in_dir = _input_dir(repo_root)
    out_dir = _output_dir(repo_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 直近アップロードを優先（原稿.csv がロックされて更新できないケースの救済）
    global _LAST_UPLOADED_SCRIPT_CSV
    script_path = None
    with _CSV_LOCK:
        if _LAST_UPLOADED_SCRIPT_CSV and _LAST_UPLOADED_SCRIPT_CSV.exists():
            script_path = _LAST_UPLOADED_SCRIPT_CSV
    if script_path is None:
        script_path = in_dir / "原稿.csv"

    if not script_path.exists():
        raise HTTPException(status_code=404, detail=f"原稿CSVが見つかりません: {script_path}")

    # tempは全削除（wav等の中間生成物）
    clear_temp_folder(str(out_dir / "temp"))

    speaker: Optional[Path] = None
    if req.speaker_wav:
        p = Path(req.speaker_wav)
        speaker = p if p.is_absolute() else (repo_root / p).resolve()
        if not speaker.exists():
            raise HTTPException(status_code=400, detail=f"speaker_wavが見つかりません: {speaker}")
    else:
        speaker = pick_default_speaker_wav()

    if not speaker:
        raise HTTPException(status_code=400, detail="話者サンプルが見つかりません。録音して sample_01.wav 等を作成してください")

    try:
        vg = get_voice_generator()
        generated = await asyncio.to_thread(
            vg.generate_from_csv,
            script_csv_path=script_path,
            speaker_wav=speaker,
            output_dir=out_dir,
            overwrite=req.overwrite,
        )
        items = []
        for p in generated:
            audio_url = ""
            try:
                rel = p.relative_to(repo_root)
                audio_url = f"/{rel.as_posix()}"
            except Exception:
                audio_url = ""
            # slide_000.mp3 → index 抽出
            m = re.match(r"^slide_(\d+)\.mp3$", p.name, flags=re.IGNORECASE)
            idx = int(m.group(1)) if m else -1
            items.append({"index": idx, "audio_url": audio_url, "path": str(p)})
        return {"ok": True, "count": len(items), "items": items, "speaker_wav": str(speaker)}
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"一括生成エラー: {e}")


@app.post("/api/clear_temp")
def clear_temp(req: ClearTempRequest) -> JSONResponse:
    """output/temp を削除して再作成する。

    要件:
      - 画像・音声生成ボタン実行時に output\\temp 内の全ファイルを削除し、上書き更新できること。
    """
    repo_root = _repo_root()
    out_dir = _output_dir(repo_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    temp_root = out_dir / "temp"
    if req.scope:
        scope = _sanitize_filename(req.scope)
        target = temp_root / scope
    else:
        target = temp_root

    ok = clear_temp_folder(str(target))
    return JSONResponse({"ok": bool(ok), "cleared": str(target)})


# APIより後に static をマウント（/api を潰さない）
app.mount("/", StaticFiles(directory=str(_repo_root()), html=True), name="static")
