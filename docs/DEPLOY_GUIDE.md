# デプロイガイド (GitHub Pages + ローカルバックエンド)

**バージョン**: 1.0.0  
**日付**: 2026-01-05  
**リポジトリ**: https://github.com/J1921604/MyVoice-Maker

## アーキテクチャ概要
- フロントエンド: 静的 `index.html` を GitHub Pages で配信
- バックエンド: ローカル FastAPI (`src/server.py`)、**Coqui TTS (XTTS v2)** による音声生成と動画合成を担当
- 通信: ブラウザから `http://127.0.0.1:8000` へアクセス（CORS不要の同一オリジンを推奨）

```mermaid
flowchart LR
    A[GitHub Pages
    index.html] --> B[ブラウザ]
    B --> C[ローカルFastAPI
    http://127.0.0.1:8000]
    C --> D[output/
    WebM/MP4]
    C --> E[input/
    PDF・原稿.csv]
```

## GitHub Pages デプロイ手順
1. `main` ブランチへ push すると `Deploy GitHub Pages` ワークフローが実行されます。
2. ワークフローは `index.html`, `docs/`, `specs/`, `README.md` を `dist/` にコピーし、Pagesへ公開します。
3. 公開URLは Actions 実行ログの `page_url` を参照してください。

### 手動でdistを用意する場合
```bash
mkdir -p dist
cp index.html dist/
cp -r docs dist/docs
cp -r specs dist/specs
cp README.md dist/README.md
```
作成したdistを `actions/upload-pages-artifact` でアップロードし、`actions/deploy-pages` で公開します。

### 手動トリガー
- GitHub Actions 画面で `Deploy GitHub Pages` を選択し、`Run workflow` をクリック。

## ローカルバックエンド起動

### 前提条件
- Python 3.10.11インストール済み
- Coqui TTS用の音声サンプル（`src/voice/models/samples/sample.wav`）が必要
  - 録音方法: `py -3.10 src\voice\create_voice.py`
  - 10-30秒の自分の声を録音
  - Web UIの録音ボタンを使う場合: ブラウザ録音（WebM等）をサーバーがFFmpegでPCM WAVに変換し、最終的に `sample.wav` に保存します

### ワンクリック（推奨）
```powershell
powershell -ExecutionPolicy Bypass -File start.ps1
```
- ポート8000を解放し、仮想環境を自動作成/起動、依存パッケージをインストール、FastAPIを起動してブラウザで `index.html` を開きます。
- **初回起動時**: Coqui TTSモデルダウンロードに30-60秒かかります

### 手動起動
```powershell
py -3.10 -m uvicorn src.server:app --host 127.0.0.1 --port 8000
start http://127.0.0.1:8000/index.html
```

## 動作手順（フロントエンド）
1. ヘッダー左の **PDF入力** でPDFを選択（input/に保存され、スライド展開されます）
2. **原稿CSV入力** でCSVを読み込み、毎回 `input/原稿.csv` に上書き保存
3. 解像度・字幕ON/OFF・動画形式(WebM/MP4)を選択
4. **画像・音声生成** で `output/temp/{scope}` をクリアしつつ素材を再生成（連続実行時のロック/混線を回避）
5. **動画生成** で `output/<PDF名>.webm|mp4` を上書き生成（字幕ONならASS焼き込み）
6. **動画出力** で output フォルダ内の動画をダウンロード
7. **PPTX出力** や **原稿CSV出力** も利用可能

## 環境変数（性能/画質チューニング）
| 変数 | 既定値 | 説明 |
|---|---|---|
| USE_COQUI_TTS | 1 | Coqui TTS使用（`0`で無効化） |
| COQUI_SPEAKER_WAV | `src/voice/models/samples/sample.wav` | 音声サンプルパス |
| USE_VP8 | 1 | `1`でVP8高速、`0`でVP9高品質 |
| VP9_CPU_USED | 8 | VP9速度パラメータ (0-8) |
| VP9_CRF | 40 | VP9品質（大きいほど軽量） |
| OUTPUT_FPS | 30 | 出力FPS（字幕切替のため30fps推奨） |
| OUTPUT_MAX_WIDTH | 1280 | 出力最大幅（px） |
| SLIDE_RENDER_SCALE | 1.5 | PDF→画像のスケール |
| SILENCE_SLIDE_DURATION | 5 | 原稿なしスライド秒数 |
| SUBTITLE_MARGIN_V | 10 | 字幕の縦マージン |
| SUBTITLE_ALIGNMENT | 2 | 字幕の配置(ASS Alignment) |

## よくある質問
- **Pages公開後にバックエンドが見つからない**: Pagesは静的配信のみです。ローカルでFastAPIを起動してください。
- **音声生成が「signal is aborted without reason」で失敗**: Coqui TTSの初回実行時はモデルダウンロードに30-60秒かかります。タイムアウトは300秒に設定済みです。
- **音声サンプルが見つからない**: `py -3.10 src\voice\create_voice.py` を実行して自分の声を録音してください。
- **動画生成が遅い**: `USE_VP8=1`, `OUTPUT_MAX_WIDTH` を下げる, `OUTPUT_FPS` を下げると高速化します。
- **字幕が切り替わらない**: 句読点でチャンク分割し、最小セグメント幅0.15秒を確保するASSを生成しています。CSVの句読点を確認してください。FPSを30fpsにすることで改善します。

## リンク
- リポジトリ: https://github.com/J1921604/MyVoice-Maker
- 完全仕様書: https://github.com/J1921604/MyVoice-Maker/blob/main/docs/%E5%AE%8C%E5%85%A8%E4%BB%95%E6%A7%98%E6%9B%B8.md
- 仕様 (spec): https://github.com/J1921604/MyVoice-Maker/blob/main/specs/001-MyVoice-Maker/spec.md
- 計画 (plan): https://github.com/J1921604/MyVoice-Maker/blob/main/specs/001-MyVoice-Maker/plan.md
- タスク (tasks): https://github.com/J1921604/MyVoice-Maker/blob/main/specs/001-MyVoice-Maker/tasks.md
