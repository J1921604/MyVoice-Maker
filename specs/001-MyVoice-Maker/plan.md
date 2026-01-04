# 実装計画: MyVoice Maker

**ブランチ**: `001-MyVoice-Maker`
**日付**: 2026-1-5
**リポジトリ**: https://github.com/J1921604/MyVoice-Maker
**仕様**: https://github.com/J1921604/MyVoice-Maker/blob/main/specs/001-MyVoice-Maker/spec.md

## 概要

本計画は、MyVoice Makerツールに以下の機能を追加するための実装計画である:

1. **音声サンプル録音機能**: 3-300秒の手動録音時間設定
2. **原稿CSV入力機能**: UTF-8/Shift-JIS対応のCSVアップロード
3. **音声生成機能**: Coqui TTS (XTTS v2)による自分の声での音声生成
4. **temp上書き更新機能**: 毎回のビルド時にtempフォルダをクリア（リトライ機能付き）
5. **タイムアウト対策**: 長文の自動分割と120秒タイムアウト設定

加えて、運用上の要件として以下も満たす:

- 原稿CSV入力でinput/原稿.csv上書き、音声生成でCoqui TTS実行、output/tempにmp3出力
- **Web UIはサーバー連携のみ（静的配信はGitHub Pages、APIはローカル）**
- **録音ファイルをsrc/voice/models/samples/に保存**
- **CSV読み込み時のエンコーディングエラーを回避**（UTF-8/Shift-JIS自動判定）
- 変更内容を **E2Eテストへ反映**し、検証可能にする

## 技術コンテキスト

**言語/バージョン**: Python 3.10.11
**主要依存関係**: TTS (Coqui XTTS v2), soundfile, imageio-ffmpeg, fastapi, uvicorn, torch, torchaudio, cutlet, unidic-lite
**ストレージ**: ファイルシステム（output/temp/, src/voice/models/samples/）
**テスト**: 手動テスト + E2Eスクリプト
**ターゲットプラットフォーム**: Windows
**プロジェクト種別**: single（Python CLI + Web UI）
**パフォーマンス目標**: 1行あたり30秒以内で音声生成
**制約**: UTF-8エンコーディング必須、メモリ使用量はテキストサイズの10倍以内
**規模/スコープ**: 個人/小規模チーム向け、1～100行のCSV対応

## 憲法チェック

| 原則 | 確認項目 | 状態 |
|------|----------|------|
| I. テスト駆動開発 | テスト作成計画が含まれているか | ✅ |
| II. セキュリティ最優先 | セキュリティ要件が機能要件より優先されているか | ✅ |
| III. パフォーマンス基準 | 定量的なパフォーマンス目標が定義されているか | ✅ |
| IV. 品質と一貫性 | UTF-8エンコーディング、依存バージョン固定が確認されているか | ✅ |
| V. シンプルさの追求 | YAGNI原則に従い、複雑さの正当化が必要か | ✅ |

**制約確認**:

- [x] 機密データの平文保存がないこと
- [x] 外部依存がバージョン固定されていること
- [x] 仕様と実装の乖離がレビューで検知可能であること

## プロジェクト構造

### ドキュメント（本機能）

```text
specs/001-MyVoice-Maker/
├── spec.md              # 機能仕様書
├── plan.md              # 本ファイル（実装計画）
├── tasks.md             # タスク一覧
├── research.md          # 調査結果（Phase 0出力）
├── data-model.md        # データモデル（Phase 1出力）
├── quickstart.md        # クイックスタート（Phase 1出力）
└── contracts/           # API契約（Phase 1出力）
```

### ソースコード（リポジトリルート）

```text
Slide-MyVoice-Maker/
├── index.html           # Web UI（サーバー連携、GitHub Pages静的配信）
├── start.ps1            # ワンクリック起動スクリプト
├── requirements.txt     # Python依存パッケージ
├── preview.bat          # プレビュー起動
├── input/
│   ├── *.pdf            # 入力PDFファイル
│   └── 原稿.csv         # ナレーション原稿
├── output/
│   ├── *.webm / *.mp4   # 生成された動画
│   └── temp/            # 一時ファイル（自動クリア対象）
├── src/
│   ├── main.py          # CLIエントリポイント
│   ├── processor.py     # PDF処理・動画生成
│   └── server.py        # FastAPIサーバー
└── tests/
    └── e2e/
        ├── test_resolution.py      # CLI解像度E2Eテスト
        └── test_local_backend.py   # バックエンドE2Eテスト

pytest.ini               # pytest設定（markers等）
```

## 実装アーキテクチャ

```mermaid
flowchart TB
    subgraph CLI入力
        ARG[--resolution引数]
        ENV[OUTPUT_MAX_WIDTH環境変数]
    end

    subgraph src/main.py
        PARSER[argparse解析]
        RESMAP[RESOLUTION_MAP]
        SETENV[環境変数設定]
    end

    subgraph src/processor.py
        CLEAR[clear_temp_folder]
        WIDTH[_get_output_max_width]
        ENCODE[動画エンコード]
    end

    subgraph Web UI index.html
        DROPDOWN[解像度ドロップダウン]
        STATE[selectedResolution state]
        API[サーバーAPI呼び出し]
    end

    subgraph src/server.py
        UPLOAD[PDF/CSVアップロード]
        GENERATE[動画生成エンドポイント]
        DOWNLOAD[ダウンロードエンドポイント]
    end

    ARG --> PARSER
    PARSER --> RESMAP
    RESMAP --> SETENV
    SETENV --> ENV
    ENV --> WIDTH
    WIDTH --> ENCODE

    DROPDOWN --> STATE
    STATE --> API
    API --> GENERATE
    GENERATE --> ENCODE
    UPLOAD --> GENERATE
```

## データフロー

```mermaid
sequenceDiagram
    participant User as ユーザー
    participant Main as main.py
    participant Proc as processor.py
    participant TTS as Edge TTS
    participant FFmpeg as FFmpeg

    User->>Main: --resolution 1080 指定
    Main->>Main: RESOLUTION_MAP参照
    Main->>Main: OUTPUT_MAX_WIDTH=1920 設定
    Main->>Proc: process_pdf_and_script()
    Proc->>Proc: clear_temp_folder()
    Proc->>Proc: PDF→画像変換
    Proc->>TTS: 音声生成リクエスト
    TTS-->>Proc: 音声ファイル
    Proc->>Proc: _get_output_max_width()→1920
    Proc->>FFmpeg: エンコード（1920x1080）
    FFmpeg-->>Proc: WebMファイル
    Proc-->>Main: 完了
    Main-->>User: 動画出力完了
```

## 状態遷移

```mermaid
stateDiagram-v2
    [*] --> 待機中: アプリ起動

    待機中 --> 入力確認中: PDF/CSV選択
    入力確認中 --> エラー: 入力不正
    入力確認中 --> 解像度選択中: 入力OK

    解像度選択中 --> 処理中: 生成開始
    処理中 --> temp削除中: clear_temp_folder
    temp削除中 --> PDF変換中: 削除完了
    PDF変換中 --> 音声生成中: 変換完了
    音声生成中 --> エンコード中: 音声完了
    エンコード中 --> 完了: エンコード完了
    エンコード中 --> エラー: エンコード失敗

    エラー --> 待機中: リトライ
    完了 --> 待機中: 新規生成
    完了 --> [*]: 終了
```

## 複雑さの追跡

本実装は既存コードへの最小限の変更で実現するため、追加の複雑さはない。

| 項目 | 判定 |
|------|------|
| 新規パターン導入 | なし |
| 外部依存追加 | なし（shutil標準ライブラリのみ） |
| アーキテクチャ変更 | なし |

## Phase 0: 調査

### 解決済み事項

| 項目 | 決定 | 根拠 |
|------|------|------|
| 解像度指定方式 | 環境変数OUTPUT_MAX_WIDTH | 既存実装との互換性維持 |
| temp削除方式 | shutil.rmtree() | 標準ライブラリで信頼性高い |
| UI解像度 | React state + select要素 | 既存UIパターンに合致 |

### 調査結果

- 解像度はアスペクト比16:9を維持（720p=1280x720, 1080p=1920x1080, 1440p=2560x1440）
- VP8/VP9エンコードは解像度に応じて自動スケーリング
- tempフォルダはPDF名ごとにサブフォルダを作成

## Phase 1: 設計

### 解像度選択機能

**Python版（src/main.py）**:
- `--resolution` 引数追加（720/720p/1080/1080p/1440/1440p）
- `RESOLUTION_MAP` で引数値を環境変数値に変換
- `os.environ["OUTPUT_MAX_WIDTH"]` に設定

**Web UI（index.html）**:
- `selectedResolution` state追加（デフォルト: '720p'）
- `RESOLUTION_OPTIONS` 配列で選択肢定義
- サーバーAPIに解像度パラメータを送信

### temp上書き機能

**src/processor.py**:
- `clear_temp_folder(temp_dir)` 関数追加
- `shutil.rmtree()` でフォルダ削除
- `os.makedirs()` で再作成
- ファイルロック時のエラーハンドリング

## Phase 2: 実装

タスク詳細は https://github.com/J1921604/Slide-MyVoice-Maker/blob/main/specs/001-Slide-MyVoice-Maker/tasks.md を参照。

## 検証計画

| テスト種別 | 内容 | 担当 |
|------------|------|------|
| 単体テスト | clear_temp_folder()の動作確認 | 自動 |
| CLI E2Eテスト | --resolution 1080で動画生成 | 自動 |
| バックエンドE2Eテスト | サーバー経由でPDF/CSV→WebM生成 | 自動 |
| 回帰テスト | 既存機能（デフォルト設定）の動作確認 | 手動 |

## リスクと対策

| リスク | 影響度 | 対策 |
|--------|--------|------|
| 高解像度でメモリ不足 | 中 | 1440p使用時の警告表示 |
| tempファイルロック | 低 | エラーログ出力して続行 |
| ブラウザ互換性 | 低 | Chrome/Edge最新版を推奨 |
