import os
import re
import sys
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# srcフォルダをパスに追加（相対インポート対応）
sys.path.insert(0, str(Path(__file__).parent))
from processor import clear_temp_folder, process_pdf_and_script, generate_single_audio, combine_audio_video


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


app = FastAPI(title="Slide Voice Maker Local API")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/warmup_tts")
async def warmup_tts() -> dict[str, str]:
    """Coqui TTSモデルを事前ロードする（初回アクセス高速化）"""
    try:
        from processor import _get_tts_model
        _get_tts_model()  # モデルをキャッシュにロード
        return {"status": "ready", "message": "Coqui TTS model loaded successfully"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _sanitize_filename(name: str) -> str:
    # すごく雑に危険文字だけ落とす（Windows/Unix両方を意識）
    name = name.strip().replace("\\", "_").replace("/", "_")
    name = re.sub(r"[\x00-\x1f<>:\"|?*]", "_", name)
    if not name:
        raise HTTPException(status_code=400, detail="ファイル名が不正です")
    return name


@app.post("/api/upload/pdf")
async def upload_pdf(file: UploadFile = File(...)) -> dict[str, str]:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="PDFファイルを指定してください")

    repo_root = _repo_root()
    in_dir = _input_dir(repo_root)
    in_dir.mkdir(parents=True, exist_ok=True)

    filename = _sanitize_filename(Path(file.filename).name)
    dst = in_dir / filename

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="PDFが空です")

    dst.write_bytes(data)
    return {"saved": str(dst), "filename": filename}


@app.post("/api/upload/csv")
async def upload_csv(file: UploadFile = File(...)) -> dict[str, str]:
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="CSVファイルを指定してください")

    repo_root = _repo_root()
    in_dir = _input_dir(repo_root)
    in_dir.mkdir(parents=True, exist_ok=True)

    dst = in_dir / "原稿.csv"
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="CSVが空です")

    dst.write_bytes(data)
    return {"saved": str(dst), "filename": dst.name}


@app.post("/api/upload/recording")
async def upload_recording(file: UploadFile = File(...)) -> dict[str, str]:
    """録音ファイルをsrc/voice/models/samples/に保存"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="ファイル名が指定されていません")

    repo_root = _repo_root()
    samples_dir = repo_root / "src" / "voice" / "models" / "samples"
    samples_dir.mkdir(parents=True, exist_ok=True)

    # ファイル名をサニタイズ
    filename = _sanitize_filename(Path(file.filename).name)
    
    # .wav拡張子を確認
    if not filename.lower().endswith('.wav'):
        filename = filename + '.wav'
    
    dst = samples_dir / filename
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="ファイルが空です")

    dst.write_bytes(data)
    return {"saved": str(dst), "filename": filename}


class GenerateRequest(BaseModel):
    pdf_name: str
    resolution: Literal["720", "720p", "1080", "1080p", "1440", "1440p"] = "720p"


class GenerateAudioRequest(BaseModel):
    output_name: Optional[str] = None  # tempスコープ（PDF名など）。未指定なら従来通り output/temp
    slide_index: int
    script: str
    image_data: Optional[str] = None  # Base64エンコードされた画像データ
    resolution: Literal["720", "720p", "1080", "1080p", "1440", "1440p"] = "720p"


class ScriptItem(BaseModel):
    index: int
    script: str


class GenerateVideoRequest(BaseModel):
    resolution: Literal["720", "720p", "1080", "1080p", "1440", "1440p"] = "720p"
    output_name: Optional[str] = "output"  # 出力ファイル名（拡張子なし）
    subtitle: bool = True  # 字幕ON/OFF
    slides_count: Optional[int] = None  # 期待スライド数（旧ファイル混入の防御）
    format: Literal["webm", "mp4"] = "webm"  # 出力形式
    scripts: Optional[list[ScriptItem]] = None  # UI上の原稿（index,script）。指定時は input/原稿.csv より優先。


class ClearTempRequest(BaseModel):
    scope: Optional[str] = None  # None なら output/temp を全削除。指定時は output/temp/<scope> のみ


@app.post("/api/generate")
async def generate(req: GenerateRequest) -> dict[str, str]:
    repo_root = _repo_root()
    in_dir = _input_dir(repo_root)
    out_dir = _output_dir(repo_root)

    pdf_name = _sanitize_filename(req.pdf_name)
    if not pdf_name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="pdf_nameは .pdf を指定してください")

    pdf_path = in_dir / pdf_name
    script_path = in_dir / "原稿.csv"

    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail=f"PDFが見つかりません: {pdf_path}")
    if not script_path.exists():
        raise HTTPException(status_code=404, detail=f"原稿CSVが見つかりません: {script_path}")

    out_dir.mkdir(parents=True, exist_ok=True)

    # 解像度→環境変数
    width = RESOLUTION_MAP.get(req.resolution, 1280)
    os.environ["OUTPUT_MAX_WIDTH"] = str(width)

    base_name = pdf_path.stem
    temp_dir = out_dir / "temp" / base_name
    clear_temp_folder(str(temp_dir))

    await process_pdf_and_script(str(pdf_path), str(script_path), str(out_dir))

    webm = out_dir / f"{base_name}.webm"
    if not webm.exists() or webm.stat().st_size == 0:
        raise HTTPException(status_code=500, detail="動画webmの生成に失敗しました")

    return {"webm": webm.name, "path": str(webm)}


@app.post("/api/generate_audio")
async def generate_audio(req: GenerateAudioRequest) -> dict[str, str]:
    """単一スライドの音声と画像を保存"""
    import base64
    
    repo_root = _repo_root()
    out_dir = _output_dir(repo_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    scope = None
    if req.output_name:
        # output_nameはフォルダ名にも使うのでサニタイズ
        scope = _sanitize_filename(req.output_name)

    temp_dir = (out_dir / "temp" / scope) if scope else (out_dir / "temp")
    temp_dir.mkdir(parents=True, exist_ok=True)

    # 画像を保存（動画生成に必要）
    if req.image_data:
        try:
            # data:image/png;base64,... 形式をパース
            if ',' in req.image_data:
                image_b64 = req.image_data.split(',', 1)[1]
            else:
                image_b64 = req.image_data
            image_bytes = base64.b64decode(image_b64)
            image_path = temp_dir / f"slide_{req.slide_index:03d}.png"
            image_path.write_bytes(image_bytes)
        except Exception as e:
            print(f"Warning: Failed to save image: {e}")

    # 原稿が空の場合は画像のみ保存（音声なし）
    if not req.script or not req.script.strip():
        return {"audio_url": "", "path": ""}

    try:
        audio_path = await generate_single_audio(
            req.slide_index,
            req.script,
            str(out_dir),
            temp_dir=str(temp_dir),
        )
        if audio_path:
            # ブラウザからアクセス可能なURLを返す
            relative_path = Path(audio_path).relative_to(repo_root)
            return {"audio_url": f"/{relative_path.as_posix()}", "path": audio_path}
        else:
            return {"audio_url": "", "path": ""}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"音声生成エラー: {str(e)}")


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


@app.post("/api/generate_video")
async def generate_video(req: GenerateVideoRequest) -> dict[str, str]:
    """output/temp内のファイルから動画を生成"""
    repo_root = _repo_root()
    out_dir = _output_dir(repo_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    width = RESOLUTION_MAP.get(req.resolution, 1280)
    
    # 出力ファイル名（PDFと同名）
    output_name = _sanitize_filename(req.output_name) if req.output_name else "output"

    out_format = (req.format or "webm").lower().strip()

    try:
        script_override = None
        if req.scripts is not None:
            script_override = {int(s.index): ("" if s.script is None else str(s.script)) for s in req.scripts}

        video_path = combine_audio_video(
            str(out_dir),
            width,
            output_name,
            req.subtitle,
            slides_count=req.slides_count,
            output_format=out_format,
            script_data_override=script_override,
        )
        video = Path(video_path)
        if video.exists() and video.stat().st_size > 0:
            # 後方互換: webmの場合はwebmキーも返す
            payload: dict[str, str] = {"filename": video.name, "path": str(video)}
            if video.suffix.lower() == ".webm":
                payload["webm"] = video.name
            if video.suffix.lower() == ".mp4":
                payload["mp4"] = video.name
            return payload
        else:
            raise HTTPException(status_code=500, detail="動画生成に失敗しました")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"動画生成エラー: {str(e)}")


@app.get("/api/list_outputs")
def list_outputs() -> dict[str, list[str]]:
    repo_root = _repo_root()
    out_dir = _output_dir(repo_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    webm_files = sorted([p.name for p in out_dir.glob("*.webm")])
    mp4_files = sorted([p.name for p in out_dir.glob("*.mp4")])
    return {"webm": webm_files, "mp4": mp4_files}


@app.get("/api/download")
def download(name: str) -> FileResponse:
    repo_root = _repo_root()
    out_dir = _output_dir(repo_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    safe = _sanitize_filename(name)
    lower = safe.lower()
    if not (lower.endswith(".webm") or lower.endswith(".mp4")):
        raise HTTPException(status_code=400, detail=".webm または .mp4 を指定してください")

    path = out_dir / safe
    if not path.exists():
        raise HTTPException(status_code=404, detail="指定ファイルが見つかりません")

    media_type = "video/webm" if lower.endswith(".webm") else "video/mp4"
    return FileResponse(path=str(path), media_type=media_type, filename=safe)


# APIより後に static をマウント（/api を潰さない）
app.mount("/", StaticFiles(directory=str(_repo_root()), html=True), name="static")
