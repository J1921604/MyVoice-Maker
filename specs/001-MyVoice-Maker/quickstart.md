# クイックスタート: MyVoice Maker

**日付**: 2026-01-05
**対象**: 開発者・利用者

## 概要

MyVoice Makerは、**原稿CSV** と **話者サンプル（自分の声）** から、Coqui TTS (XTTS v2) を用いて **MP3音声**（`output/slide_000.mp3` など）を自動生成するローカルツールです。

※ 本プロジェクトは **音声生成専用** です。

## 動作環境

| 項目 | 要件 |
|------|------|
| OS | Windows 10/11 |
| Python | 3.10.11（推奨） |
| ブラウザ | Chrome / Edge（最新版） |
| マイク | 録音機能を使う場合に必要 |

## インストール

### 1. リポジトリクローン

```bash
git clone https://github.com/J1921604/MyVoice-Maker.git
cd MyVoice-Maker
```

### 2. 依存パッケージインストール

```bash
py -3.10 -m pip install -r requirements.txt
```

## 使い方（Web UI・推奨）

### 起動

```powershell
powershell -ExecutionPolicy Bypass -File start.ps1
```

ブラウザで以下を開きます:

- http://127.0.0.1:8000

### 手順

1. （初回のみ）必要に応じて「TTSウォームアップ」を実行
2. 「録音」から自分の声を録音して保存（`src/voice/models/samples/sample_01.wav` など）
3. 「原稿CSV入力」で `input/原稿.csv` をアップロード（UI上で編集も可能）
4. 「音声生成」を実行
	- 実行前に `output/temp/` は自動クリアされ、中間生成物（WAVなど）は残りません
	- 生成されたMP3は `output/slide_000.mp3` などとして **上書き保存**されます
5. 生成された音声を再生／ダウンロード

## 使い方（CLI）

```bash
# input/原稿.csv を output/ に一括生成（上書きあり）
py -3.10 src\main.py

# 出力先を変更
py -3.10 src\main.py --output .\output

# 話者サンプルを明示指定
py -3.10 src\main.py --speaker-wav .\src\voice\models\samples\sample_01.wav

# 既存ファイルを上書きしない
py -3.10 src\main.py --no-overwrite
```

## 入力

### 原稿CSV

**ファイル**: `input/原稿.csv`

**形式**:

```csv
index,script
0,"最初の原稿テキストをここに記載します。"
1,"2行目の原稿です。"
```

| 列名 | 説明 |
|------|------|
| index | 音声の連番（0始まり） |
| script | 読み上げテキスト |

**対応文字コード**: UTF-8（推奨）、Shift_JIS/CP932 ほか（サーバー側で自動判定）

### 話者サンプル

- 保存先: `src/voice/models/samples/`
- ファイル名: `sample_01.wav`, `sample_02.wav` ...（**上書き禁止**で連番保存）
- 既定: 最大番号（最新）の `sample_XX.wav` が自動選択されます

## 出力

- `output/slide_000.mp3`, `output/slide_001.mp3` ...（実行ごとに上書き）
- `output/temp/` は中間生成物用（実行前に自動クリア）

## 環境変数

| 変数名 | デフォルト | 説明 |
|--------|-----------|------|
| `SVM_INPUT_DIR` | `./input` | 入力ディレクトリ（テスト・運用用） |
| `SVM_OUTPUT_DIR` | `./output` | 出力ディレクトリ（テスト・運用用） |
| `SVM_FAKE_TTS` | 未設定 | `1` の場合、モデル無しで疑似生成（テスト用） |

## トラブルシューティング

| 症状 | 原因 | 対処 |
|------|------|------|
| UIが通信できない | `index.html` を直接開いている（`file://`） | `start.ps1` で起動し、`http://127.0.0.1:8000` から開く |
| CSVが保存できない | 他アプリで開いてロックされている | ロックを解除して再試行（サーバーはユニーク名にも保存します） |
| tempが消えない | プレビュー等でファイルロック | 関連アプリを閉じて再実行（サーバー側でリトライします） |
| 生成に時間がかかる | 初回のモデルロードが重い | 先に「ウォームアップ」を実行、もしくは待機（UIは最大600秒） |

## 次のステップ

- [機能仕様書](https://github.com/J1921604/MyVoice-Maker/blob/main/specs/001-MyVoice-Maker/spec.md)を確認
- [実装計画](https://github.com/J1921604/MyVoice-Maker/blob/main/specs/001-MyVoice-Maker/plan.md)を確認
- [タスク一覧](https://github.com/J1921604/MyVoice-Maker/blob/main/specs/001-MyVoice-Maker/tasks.md)で進捗確認
