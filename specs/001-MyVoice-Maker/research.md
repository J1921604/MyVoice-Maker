# 調査結果: MyVoice Maker

**日付**: 2026-01-05
**Phase**: 0 - 調査

## 調査概要

本ドキュメントは、MyVoice Maker（`index.html` + `src/server.py` + `src/voice/voice_generator.py`）における、
**UIの固着/無反応**・**CSV文字化け**・**録音保存**・**音声生成タイムアウト**の再発防止のための技術判断をまとめる。

## 調査項目と決定

### 1. Web UI が「無反応」に見える原因

**原因候補**:

- `file://` で `index.html` を直接開くと `window.location.origin === "null"` となり、API URL が壊れて通信できない。
- FastAPI の `async` エンドポイント内で、Coqui XTTS v2 のモデルロード/推論を同期実行すると **イベントループがブロック**され、
  その間の `/api/upload/csv` などが応答不能に見える。
- JS例外が発生するとイベントハンドラが登録されず、クリックが「無反応」に見える。

**決定**:

- UI側: `origin === "null"` のとき `http://127.0.0.1:8000` を API_BASE とする。
- サーバー側: 重い処理（モデルロード/推論/FFmpeg変換）は `asyncio.to_thread(...)` でスレッドへ逃がす。
- UI側: `window.onerror` / `unhandledrejection` でステータス欄へエラーを表示する。

---

### 2. tempクリア失敗（Windowsのファイルロック）

**課題**:

- ブラウザの音声プレビュー等で `output/temp` 配下のファイルがロックされると、削除に失敗しうる。

**決定**:

- `output/temp` は **毎回全削除→再作成**する（中間生成物の残存を防ぐ）。
- UI は音声生成の直前に API `POST /api/clear_temp` を呼び出し、失敗時は生成を開始しない。

---

### 3. ブラウザ録音は WAV にならない

**事実**:

- `MediaRecorder` の録音データは環境依存の形式になり、WAV とは限らない。
- そのまま保存すると XTTS が読み込めず、エラーや沈黙の原因になりうる。

**決定**:

- UI は録音データをアップロードする。
- サーバーは FFmpeg で **PCM 16-bit mono WAV（24kHz/mono）** に変換し、`src/voice/models/samples/sample_01.wav` などとして **上書き禁止**で保存する。

---

### 4. CSV解析

**課題**:

- `split("\n")` + 正規表現の簡易解析では、引用符・カンマ・改行を含むセルで破綻する。
- UTF-8 と Shift_JIS の判定は「例外」では検出できない（UTF-8のデコードは通常例外を投げない）。

**決定**:

- UI側で最小限の RFC4180 対応パーサを実装し、引用符/カンマ/改行を扱う。
- UTF-8デコード結果の置換文字 $\uFFFD$ 比率で Shift_JIS 再デコードを試す。

---

### 5. CSV保存（Excel等によるロック対策）

**課題**:

- `input/原稿.csv` が他アプリで開かれていると、サーバーが上書きできない。

**決定**:

- サーバーはまずユニーク名（`input/原稿_YYYYmmdd-HHMMSS.csv`）へ保存し、可能な場合のみ `input/原稿.csv` も更新する。
- 音声一括生成は「直近にアップロードされたCSV」を優先して使用し、ロック環境でも動作する。

## 参考

- FFmpeg（`imageio-ffmpeg`）
- FastAPI async endpoint のブロッキング回避（`asyncio.to_thread`）
