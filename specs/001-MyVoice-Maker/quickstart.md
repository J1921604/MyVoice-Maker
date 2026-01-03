# クイックスタート: Slide MyVoice Maker

**日付**: 2026-1-5
**対象**: 開発者・利用者

## 概要

Slide MyVoice MakerはPDFスライドと原稿CSVから、Coqui TTS (XTTS v2)による自分の声を使ったAI音声ナレーション付き動画（WebM）を自動生成するツールです。

## 動作環境

| 項目 | 要件 |
|------|------|
| OS | Windows 10/11 |
| Python | 3.10.11（推奨） |
| ブラウザ | Chrome / Edge（最新版） |

## インストール

### 1. リポジトリクローン

```bash
git clone https://github.com/J1921604/Slide-MyVoice-Maker.git
cd Slide-MyVoice-Maker
```

### 2. 依存パッケージインストール

```bash
py -3.10 -m pip install -r requirements.txt
```

## 使用方法

### ワンクリック実行（推奨）

**Windows バッチ**:

```batch
.\start.ps1
```

**PowerShell**:

```powershell
.\start.ps1
```

### コマンドライン実行

**基本実行**:

```bash
py -3.10 src\main.py
```

**解像度指定**:

```bash
# 720p（デフォルト）
py -3.10 src\main.py --resolution 720p

# 1080p（フルHD）
py -3.10 src\main.py --resolution 1080p

# 1440p（2K）
py -3.10 src\main.py --resolution 1440p
```

**フルオプション**:

```bash
py -3.10 src\main.py --input input --output output --script input\原稿.csv --resolution 1080
```

## 入力ファイル

### PDFファイル

- `input/` フォルダに配置
- 複数PDF対応（順次処理）

### 原稿CSV

**ファイル**: `input/原稿.csv`

**形式**:

```csv
index,script
0,"最初のスライドの原稿テキストをここに記載します。"
1,"2番目のスライドの原稿です。"
2,"3番目のスライドの原稿。"
```

| 列名 | 説明 |
|------|------|
| index | スライド番号（0始まり） |
| script | 読み上げテキスト |

**対応文字コード**: UTF-8（推奨）、Shift_JIS、EUC-JP

## 出力ファイル

### 動画ファイル

- `output/{PDFファイル名}.webm`
- VP8/VP9コーデック
- 選択した解像度で出力

### 一時ファイル

- `output/temp/{PDFファイル名}/`
- 処理開始時に自動クリア

## 解像度オプション

| 選択肢 | 解像度 | 用途 |
|--------|--------|------|
| 720p | 1280×720 | Web配信、ファイルサイズ優先 |
| 1080p | 1920×1080 | プレゼンテーション、標準品質 |
| 1440p | 2560×1440 | 高品質、大画面表示 |

## Web UI

**起動方法**:
```powershell
# ワンクリック起動（推奨）
powershell -ExecutionPolicy Bypass -File start.ps1

# または手動起動
py -3.10 -m uvicorn src.server:app --host 127.0.0.1 --port 8000
```

**URL**: http://127.0.0.1:8000

### 使用手順

1. PDFファイルをアップロード
2. 原稿CSVをアップロード（input/原稿.csvに保存）
3. 解像度を選択（720p/1080p/1440p）
4. 再生速度を選択（0.5x〜2.0x）
5. 字幕ON/OFFを選択（動画に字幕を埋め込むかどうか）
6. 「画像・音声生成」ボタンをクリック（output/tempに保存）
7. 「動画生成」ボタンをクリック（output/に保存）
8. 「動画出力」ボタンで動画ダウンロード

## 環境変数

| 変数名 | デフォルト | 説明 |
|--------|-----------|------|
| `OUTPUT_MAX_WIDTH` | 1280 | 出力最大幅（px） |
| `USE_VP8` | 1 | VP8使用（0でVP9） |
| `VP9_CPU_USED` | 8 | エンコード速度（0-8） |
| `VP9_CRF` | 40 | 品質（大きいほど低品質） |
| `OUTPUT_FPS` | 15 | 出力FPS |
| `SLIDE_RENDER_SCALE` | 1.5 | PDF解像度倍率 |
| `SILENCE_SLIDE_DURATION` | 5 | 原稿なしスライド表示秒数 |

## トラブルシューティング

### よくある問題

| 症状 | 原因 | 対処法 |
|------|------|--------|
| Python not found | Pythonパスが通っていない | `py -3.10` を使用 |
| 文字化け | CSVエンコーディング | UTF-8で保存し直す |
| 動画生成が遅い | 高解像度設定 | 720pを使用、またはVP8を有効化 |
| tempファイルが消えない | ファイルロック | プレビューアプリを閉じて再実行 |

### ログ確認

```bash
# 詳細ログを表示
py -3.10 src\main.py 2>&1 | tee log.txt
```

## 次のステップ

- [機能仕様書](https://github.com/J1921604/Slide-MyVoice-Maker/blob/main/specs/001-Slide-MyVoice-Maker/spec.md)を確認
- [実装計画](https://github.com/J1921604/Slide-MyVoice-Maker/blob/main/specs/001-Slide-MyVoice-Maker/plan.md)を確認
- [タスク一覧](https://github.com/J1921604/Slide-MyVoice-Maker/blob/main/specs/001-Slide-MyVoice-Maker/tasks.md)で進捗確認
