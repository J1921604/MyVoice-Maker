import base64
import os
import socket
import subprocess
import time
from pathlib import Path

import fitz
import pytest
import requests
from PIL import Image


def _wait_port(host: str, port: int, *, timeout_s: float = 20.0) -> None:
    deadline = time.time() + timeout_s
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(0.1)
    raise TimeoutError(f"HTTPサーバーが起動しませんでした: {host}:{port} ({last_err})")


def _make_sample_pdf(path: Path, *, pages: int = 2, width: float = 1280, height: float = 720) -> None:
    doc = fitz.open()
    try:
        for i in range(pages):
            page = doc.new_page(width=width, height=height)
            page.insert_text((72, 72), f"Slide {i+1}")
        doc.save(path)
    finally:
        doc.close()


def _write_empty_csv(path: Path, pages: int) -> None:
    # Edge TTSに依存しないよう、scriptは空（ローカルでも無音MP3→WebM生成が成立する）
    lines = ["index,script"]
    for i in range(pages):
        lines.append(f"{i},\"\"")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.mark.e2e
def test_local_backend_generates_and_downloads_webm(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]

    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = tmp_path / "sample.pdf"
    csv_path = tmp_path / "原稿.csv"
    _make_sample_pdf(pdf_path, pages=2)
    _write_empty_csv(csv_path, pages=2)

    host = "127.0.0.1"
    port = 8123

    base_url = f"http://{host}:{port}"

    env = os.environ.copy()
    env["SVM_INPUT_DIR"] = str(input_dir)
    env["SVM_OUTPUT_DIR"] = str(output_dir)
    env["USE_VP8"] = "1"
    env["OUTPUT_FPS"] = "5"
    env["SLIDE_RENDER_SCALE"] = "1.5"
    # CI/ローカルいずれでも短時間で完走させる（無音スライドを短く）
    env["SILENCE_SLIDE_DURATION"] = "0.5"

    # Python 3.10 を優先（要求: python ではなく py -3.10）
    # フォールバックとして venv の python.exe も許容する（CI/環境差対策）
    venv_python = repo_root / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        cmd = [str(venv_python)]
    else:
        cmd = ["py", "-3.10"]

    server = subprocess.Popen(
        cmd
        + [
            "-m",
            "uvicorn",
            "src.server:app",
            "--host",
            host,
            "--port",
            str(port),
        ],
        cwd=str(repo_root),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        _wait_port(host, port, timeout_s=30.0)

        # index.html が配信される（UIの入口がある）こと
        r = requests.get(f"{base_url}/index.html", timeout=10)
        assert r.status_code == 200
        assert "Slide Voice Maker" in r.text

        # PDF/CSVをアップロード（input/へ保存される）
        with open(pdf_path, "rb") as f:
            r = requests.post(f"{base_url}/api/upload/pdf", files={"file": ("sample.pdf", f, "application/pdf")}, timeout=20)
        assert r.status_code == 200, r.text

        with open(csv_path, "rb") as f:
            r = requests.post(f"{base_url}/api/upload/csv", files={"file": ("原稿.csv", f, "text/csv")}, timeout=20)
        assert r.status_code == 200, r.text

        # output/temp をクリア
        r = requests.post(f"{base_url}/api/clear_temp", json={}, timeout=30)
        assert r.status_code == 200, r.text

        # 画像を2枚用意し、generate_audio（script空）で temp/<scope> に保存させる
        # ※scriptが空でもimage_data保存が成立することが要件
        def png_data_url(text: str) -> str:
            img = Image.new("RGB", (320, 180), (12, 14, 20))
            # 文字描画フォント非依存のため、ここでは描画なしでOK
            # 代わりにテキストで色を少し変えて差を出す
            if "1" in text:
                img.paste((30, 40, 70), (0, 0, 40, 40))
            else:
                img.paste((70, 40, 30), (0, 0, 40, 40))
            from io import BytesIO

            buf = BytesIO()
            img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            return f"data:image/png;base64,{b64}"

        scope = "sample"
        for i in range(2):
            payload = {
                "output_name": scope,
                "slide_index": i,
                "script": "",  # 空=音声生成なし
                "image_data": png_data_url(f"Slide {i+1}"),
                "resolution": "720p",
            }
            r = requests.post(f"{base_url}/api/generate_audio", json=payload, timeout=60)
            assert r.status_code == 200, r.text

        # 動画生成（新仕様: scripts を渡して字幕原稿がUIと一致する）
        scripts = [
            {"index": 0, "script": "今回は、AIドリブン開発が必要なのか？"},
            {"index": 1, "script": "なぜ今、AIなのか？"},
        ]

        payload = {
            "resolution": "720p",
            "output_name": scope,
            "subtitle": True,
            "slides_count": 2,
            "format": "webm",
            "scripts": scripts,
        }
        r = requests.post(f"{base_url}/api/generate_video", json=payload, timeout=180)
        assert r.status_code == 200, r.text
        j = r.json()
        assert "filename" in j
        assert j["filename"].endswith(".webm")

        # サーバーが書き込んだ output 側にもファイルがある
        generated = output_dir / "sample.webm"
        assert generated.exists(), "output/にWebMが生成されていません"
        assert generated.stat().st_size > 0, "output/のWebMが空です"

        # ダウンロードAPI
        r = requests.get(f"{base_url}/api/download", params={"name": "sample.webm"}, timeout=30)
        assert r.status_code == 200
        assert len(r.content) > 0

    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except Exception:  # noqa: BLE001
            server.kill()
