from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import uuid
import wave
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest


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


def _write_csv(path: Path) -> None:
    # サーバー側で decode + parse されることを確認する
    path.write_text("index,script\n0,\"テスト1\"\n1,\"テスト2\"\n", encoding="utf-8-sig")


def _write_wav(path: Path, *, seconds: float = 0.3, sr: int = 24000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = int(seconds * sr)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(b"\x00\x00" * frames)


def _http_get(url: str, *, timeout: float = 10) -> tuple[int, bytes]:
    req = Request(url, method="GET")
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return resp.getcode(), resp.read()


def _http_post_json(url: str, payload: dict, *, timeout: float = 30) -> tuple[int, bytes]:
    data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return resp.getcode(), resp.read()


def _http_post_multipart_file(
    url: str,
    *,
    field: str,
    filename: str,
    content_type: str,
    file_bytes: bytes,
    timeout: float = 30,
) -> tuple[int, bytes]:
    boundary = f"----svm-{uuid.uuid4().hex}"
    body = (
        f"--{boundary}\r\n"
        f"Content-Disposition: form-data; name=\"{field}\"; filename=\"{filename}\"\r\n"
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8") + file_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

    req = Request(url, data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Content-Length", str(len(body)))
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return resp.getcode(), resp.read()


@pytest.mark.e2e
def test_local_backend_uploads_csv_and_generates_mp3(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]

    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_path = tmp_path / "原稿.csv"
    _write_csv(csv_path)

    speaker = tmp_path / "speaker.wav"
    _write_wav(speaker)

    host = "127.0.0.1"
    port = 8123

    base_url = f"http://{host}:{port}"

    env = os.environ.copy()
    env["SVM_INPUT_DIR"] = str(input_dir)
    env["SVM_OUTPUT_DIR"] = str(output_dir)
    env["SVM_FAKE_TTS"] = "1"  # モデルDL無しで完走

    server = subprocess.Popen(
        [
            sys.executable,
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
        code, body = _http_get(f"{base_url}/index.html", timeout=10)
        assert code == 200
        assert b"MyVoice" in body or b"Slide Voice Maker" in body

        # PDFアップロードは410
        try:
            _http_post_multipart_file(
                f"{base_url}/api/upload/pdf",
                field="file",
                filename="sample.pdf",
                content_type="application/pdf",
                file_bytes=b"%PDF-1.4\n%...",
                timeout=10,
            )
            assert False, "expected 410"
        except HTTPError as e:
            assert e.code == 410

        # CSVアップロード（input/へ保存され、slidesが返る）
        code, body = _http_post_multipart_file(
            f"{base_url}/api/upload/csv",
            field="file",
            filename="原稿.csv",
            content_type="text/csv",
            file_bytes=csv_path.read_bytes(),
            timeout=20,
        )
        assert code == 200
        j = json.loads(body.decode("utf-8"))
        assert "slides" in j
        assert len(j["slides"]) == 2

        # output/temp をクリア
        code, _ = _http_post_json(f"{base_url}/api/clear_temp", {}, timeout=30)
        assert code == 200

        # 一括生成（speaker_wavは絶対パス指定）
        payload = {"overwrite": True, "speaker_wav": str(speaker)}
        code, body = _http_post_json(f"{base_url}/api/generate_from_csv", payload, timeout=180)
        assert code == 200
        j = json.loads(body.decode("utf-8"))
        assert j.get("ok") is True
        assert j.get("count") == 2

        out0 = output_dir / "slide_000.mp3"
        out1 = output_dir / "slide_001.mp3"
        assert out0.exists() and out0.stat().st_size > 0
        assert out1.exists() and out1.stat().st_size > 0

    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except Exception:  # noqa: BLE001
            server.kill()
