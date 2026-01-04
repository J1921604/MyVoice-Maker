# Web API契約: MyVoice Maker

**日付**: 2026-01-05
**対象**: `index.html`（Web UI）↔ `src/server.py`（FastAPI）

## 概要

Web UI は FastAPI サーバー（`src/server.py`）と同一オリジンで動作する。

- 推奨アクセス: `http://127.0.0.1:8000/`
- `file://` で `index.html` を直接開いた場合、`window.location.origin` が `"null"` になるため、UI は `http://127.0.0.1:8000` を API の接続先にフォールバックする。

## 共通

- **Base URL**: `http://127.0.0.1:8000`
- **Content-Type**:
  - JSON: `application/json`
  - ファイルアップロード: `multipart/form-data`
- **静的ファイル配信**: `/` 以下はリポジトリルートが静的にマウントされる（`output/` もブラウザから参照可能）。

## エンドポイント

### GET /api/health

サーバー死活確認。

**Response**: `200`

```json
{ "status": "ok" }
```

---

### POST /api/warmup_tts

Coqui TTS (XTTS v2) の初回ロードを先に行う。重い処理はイベントループをブロックしないようスレッドで実行される。

**Response**: `200`

```json
{ "status": "ready", "message": "Coqui TTS model loaded successfully" }
```

---

### POST /api/upload/csv

原稿CSVを `input/原稿.csv` に上書き保存する。

**Request**: `multipart/form-data`

- `file`: `.csv`

**Response**: `200`

```json
{ "saved": "...\\input\\原稿.csv", "filename": "原稿.csv" }
```

---

### POST /api/upload/recording

ブラウザ録音ファイルを受け取り、XTTS が確実に読める **PCM 16-bit mono WAV（24kHz/mono）** に変換して `src/voice/models/samples/` 配下に保存する。

保存は **上書き禁止** で、`sample_01.wav` / `sample_02.wav` ... の連番になる。

**Request**: `multipart/form-data`

- `file`: 録音ファイル（実体はFFmpegで変換する）

**Response**: `200`

```json
{ "saved": "...\\src\\voice\\models\\samples\\sample_01.wav", "filename": "sample_01.wav" }
```

---

### POST /api/clear_temp

`output/temp` の削除・再作成。

**Request (JSON)**

```json
{}
```

**Response**: `200`

```json
{ "ok": true, "cleared": "...\\output\\temp\\job_..." }
```

---

### POST /api/generate_audio

単一行の音声（MP3）を生成して `output/slide_XXX.mp3` に保存する。

**Request (JSON)**

```json
{
  "slide_index": 0,
  "script": "こんにちは",
  "overwrite": true
}
```

**Response**: `200`

```json
{ "audio_url": "/output/slide_000.mp3", "path": "...\\output\\slide_000.mp3" }
```

備考:

- 出力先がリポジトリ外（`SVM_OUTPUT_DIR` の差し替え等）で静的配信できない場合、`audio_url` は空文字になる。

---

### POST /api/generate_from_csv

`input/原稿.csv`（もしくは直近アップロードのCSV）から音声を一括生成して `output/` に保存する。

**Request (JSON)**

```json
{ "overwrite": true, "speaker_wav": null }
```

- `speaker_wav`: 指定がある場合はその話者サンプルを優先する（相対パスはリポジトリルート基準）。

**Response**: `200`

```json
{
  "ok": true,
  "count": 2,
  "items": [
    { "index": 0, "audio_url": "/output/slide_000.mp3", "path": "...\\output\\slide_000.mp3" },
    { "index": 1, "audio_url": "/output/slide_001.mp3", "path": "...\\output\\slide_001.mp3" }
  ],
  "speaker_wav": "...\\src\\voice\\models\\samples\\sample_02.wav"
}
```
