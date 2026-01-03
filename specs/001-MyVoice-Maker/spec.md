# 機能仕様書: Slide MyVoice Maker

**機能ブランチ**: `001-Slide-MyVoice-Maker`
**作成日**: 2026-1-5
**バージョン**: 1.0.0
**状態**: 承認済

## 概要

Slide MyVoice Makerは、PDFスライドと原稿CSVから、**Coqui TTS (XTTS v2)** を使用した自分の声によるAI音声ナレーション付き動画（WebM/MP4）を自動生成し、PPTXや原稿CSVとしても出力できるツールである。

本仕様では以下の機能を定義する:

1. **出力動画の解像度選択**: ユーザーが動画出力時に解像度（720p/1080p/1440p）を選択可能にする
2. **temp上書き更新**: 毎回の実行時にoutput/tempフォルダを上書き更新し、古いファイルを自動削除する

加えて、運用上の必須要件として以下を定義する:

- **機能（src/server.py起動時）**:
  - PDF入力ボタン実行で、PDFファイルをアップロードしスライドとして展開
    - 原稿CSV入力ボタン実行で、inputフォルダにCSVファイルを毎回上書き保存
    - 解像度プルダウン選択（720p/1080p/1440p）- 画像解像度
    - 再生速度プルダウン選択（0.5x〜2.0x）- 全スライドに適用
    - 字幕ON/OFFトグル - 動画に字幕を埋め込むかどうかを選択（句読点分割+文字数比率タイミング）
    - 画像・音声生成ボタン実行で、output/tempフォルダをクリアして画像・音声を上書き保存
    - 動画生成ボタン実行で、output/に動画WebM/MP4を上書き更新（PDFと同名で保存）
    - 原稿CSV出力ボタン実行で、編集した原稿をCSVでダウンロード
    - 動画出力ボタン実行で、outputフォルダに保存した動画（WebM/MP4）を選択してダウンロード
    - PPTX出力ボタン実行で、ブラウザ上のスライド画像をPPTXとしてダウンロード

- **ホーム画面ヘッダーのPDF入力ボタンで常時アップロード可能**

## プロセスフロー

```mermaid
flowchart TD
    A[PDF入力] --> B[input/保存 + スライド展開]
    B --> C[原稿CSV入力<br>input/原稿.csv上書き]
    C --> D[解像度/字幕/形式選択]
    D --> E[画像・音声生成
    output/tempクリア→素材保存]
    E --> F[動画生成 WebM/MP4
    字幕ONならASS焼き込み]
    F --> G[output/<PDF名>.webm|mp4]
    G --> H[動画出力ダウンロード]
    B --> I[PPTX出力]
```

## システムアーキテクチャ

```mermaid
flowchart TB
    subgraph ユーザー入力
        PDF[PDFファイル]
        CSV[原稿CSV]
        RES[解像度選択]
    end

    subgraph サーバー
        SERVER[src/server.py]
        MAIN[src/main.py]
        PROC[src/processor.py]
        TTS[Coqui TTS<br/>XTTS v2]
    end

    subgraph Web UI
        HTML[index.html]
        PDFJS[PDF.js]
        CSVDEC[CSVデコード<br/>TextDecoder]
    end

    subgraph 出力
        TEMP[output/temp/]
        WEBM[output/*.webm]
    end

    PDF --> HTML
    CSV --> HTML
    RES --> HTML
    HTML --> SERVER
    SERVER --> MAIN
    MAIN --> PROC
    PROC --> TTS
    PROC --> TEMP
    PROC --> WEBM
```

### ユーザーストーリー1 - 出力解像度の選択（優先度: P1）

ユーザーは動画生成前に出力解像度を選択し、用途に応じた品質の動画を生成できる。

**この優先度の理由**: プレゼンテーション用途や配信用途で異なる解像度が必要なため、最優先で実装する。

**独立テスト**: 解像度選択UIで720pを選択し、動画生成後にファイルの実解像度が1280x720であることを確認する。

**受入シナリオ**:

| 前提条件 | 操作 | 期待結果 |
|----------|------|----------|
| PDFと原稿CSVがinputフォルダにある | 解像度1080pを選択して動画生成 | 出力動画の解像度が1920x1080 |
| 解像度未選択 | 動画生成を実行 | デフォルト1280x720で動画生成 |

---

### ユーザーストーリー2 - temp上書き更新（優先度: P1）

ユーザーは毎回の実行時にtempフォルダが自動的にクリアされ、古いファイルが残らない。

**この優先度の理由**: ディスク容量の圧迫防止と、混乱の原因となる古いファイルの除去のため最優先。

**独立テスト**: 2回連続で動画生成を実行し、tempフォルダ内に1回目のファイルが残っていないことを確認する。

**受入シナリオ**:

| 前提条件 | 操作 | 期待結果 |
|----------|------|----------|
| tempフォルダに過去の生成ファイルがある | 新しいPDFで動画生成 | 過去のファイルは削除され新しいファイルのみ存在 |
| tempフォルダが存在しない | 動画生成を実行 | tempフォルダが作成されファイルが生成される |

---

### エッジケース

- 解像度選択が無効な値の場合、デフォルト720pにフォールバック
- tempフォルダ削除中にファイルがロックされている場合、エラーログを出力して続行
- 非常に大きなPDF（100ページ超）の場合、進捗表示を行う

## 機能要件

| ID | 要件 | 優先度 |
|----|------|--------|
| FR-001 | システムは720p/1080p/1440pの解像度オプションを提供しなければならない | P1 |
| FR-002 | システムはデフォルト解像度として720p（1280x720）を使用しなければならない | P1 |
| FR-003 | システムは動画生成前にtempフォルダを自動的にクリアしなければならない | P1 |
| FR-004 | システムは解像度設定を環境変数OUTPUT_MAX_WIDTHで制御可能にしなければならない | P1 |
| FR-005 | システムはindex.html（Web UI）に解像度選択UIを追加しなければならない | P1 |
| FR-006 | システムはPython版（src/main.py）にコマンドライン引数--resolutionを追加しなければならない | P1 |
| FR-007 | システムはUTF-8エンコーディングで全ファイルを処理しなければならない | P1 |
| FR-008 | システムは動画形式としてWebMとMP4を選択できなければならない | P1 |
| FR-009 | システムはヘッダーからPDFアップロードを受け付け、input/へ保存しスライド展開しなければならない | P1 |
| FR-010 | システムはPPTX出力を提供しなければならない | P2 |
| FR-011 | システムは字幕を句読点で分割し、文字数比率でタイミングを計算しなければならない | P1 |
| FR-012 | システムは字幕の最小セグメント時間を0.15秒以上とし、確実に切り替わるようにしなければならない | P1 |
| FR-013 | システムは動画出力のFPSを30fpsとし、字幕切り替わりを確保しなければならない | P1 |
| FR-014 | システムはFFmpegエンコード時に全CPUコアを活用しなければならない | P1 |

## 解像度マッピング

| 選択肢 | 幅（px） | 高さ（px） | 環境変数値 |
|--------|----------|------------|------------|
| 720p   | 1280     | 720        | 1280       |
| 1080p  | 1920     | 1080       | 1920       |
| 1440p  | 2560     | 1440       | 2560       |

## 主要エンティティ

```mermaid
erDiagram
    Resolution {
        string value "720p/1080p/1440p"
        int width "出力幅(px)"
        int height "出力高さ(px)"
        string label "表示ラベル"
    }

    TempFolder {
        string path "フォルダパス"
        bool auto_clear_on_start "開始時自動クリア"
    }

    VideoOutput {
        string filename "出力ファイル名"
        Resolution resolution "解像度設定"
        string codec "VP8/VP9"
        float duration "動画長(秒)"
    }

    Slide {
        int page_index "ページ番号"
        string image_path "画像パス"
        string audio_path "音声パス"
        string script_text "原稿テキスト"
        float duration "表示時間(秒)"
    }

    VideoOutput ||--|| Resolution : "解像度を持つ"
    VideoOutput ||--|{ Slide : "スライドを含む"
    TempFolder ||--|{ Slide : "一時ファイルを格納"
```

## 成功基準

| ID | 基準 | 測定方法 |
|----|------|----------|
| SC-001 | 解像度選択から動画生成完了まで、スライド1枚あたり10秒以内 | 処理時間計測 |
| SC-002 | temp上書きによりディスク使用量が前回生成分のみに制限される | ファイルサイズ確認 |
| SC-003 | 選択した解像度と出力動画の実解像度が100%一致する | FFmpegログ解析で検証 |
| SC-004 | Web UIで解像度選択が正常に動作する | E2Eテスト |

## 技術スタック

| 項目 | 技術 |
|------|------|
| 言語 | Python 3.10.11 |
| 音声合成 | Coqui TTS (XTTS v2) - 自分の声でクローン音声生成 |
| 動画編集 | MoviePy < 2.0 |
| PDF処理 | PyMuPDF (fitz) |
| 動画エンコード | FFmpeg (VP8/VP9/H.264) |
| Web UI | React 18 + Tailwind CSS + PDF.js |
| サーバー | FastAPI + Uvicorn |

## 依存関係

```
# 音声合成
TTS>=0.22.0                 # Coqui TTS (XTTS v2)
torch>=2.0.0                # PyTorch (Coqui TTS依存)
torchaudio>=2.0.0           # torchaudio (Coqui TTS依存)
soundfile>=0.12.1           # TorchCodecバイパス用
cutlet>=0.4.0               # 日本語ローマ字化
unidic-lite>=1.0.8          # MeCab辞書（fugashi依存）

# 動画編集
moviepy<2.0                 # 動画生成
imageio-ffmpeg>=0.4.9       # FFmpeg自動ダウンロード
pymupdf>=1.23.0             # PDF処理
Pillow>=10.0.0              # 画像処理

# Webサーバー
fastapi>=0.104.0            # REST API
uvicorn[standard]>=0.24.0   # ASGIサーバー

# ユーティリティ
requests>=2.31.0            # HTTP通信
pytest>=7.4.0               # テスト
```
