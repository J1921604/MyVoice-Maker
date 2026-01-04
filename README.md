# MyVoice Maker

原稿CSVから、AI音声ナレーション（MP3）を自動生成するツールです。

**バージョン**: 1.0.0  
**日付**: 2026-1-5  
**リポジトリ**: https://github.com/J1921604/MyVoice-Maker

## 🎯 音声生成技術

### Coqui TTS (XTTS v2)

このプロジェクトは **Coqui TTS（XTTS v2）** を使用して、あなた自身の声を使った音声ナレーションを生成します。

```mermaid
flowchart LR
    A[音声サンプル<br/>sample.wav] --> B[XTTS v2<br/>モデル]
    C[原稿テキスト] --> B
    B --> D[生成音声<br/>*.mp3]
```

#### 特徴

- **自分の声**: わずか3-10秒の音声サンプルで、あなたの声を再現
- **多言語対応**: 日本語を含む複数言語に対応
- **オープンソース**: 完全にオープンソースで、ローカル実行可能
- **高品質**: 自然な抑揚とイントネーションを再現

#### 音声サンプル作成

```bash
# 音声サンプルを録音
py -3.10 src\voice\create_voice.py
```

録音後、`src/voice/models/samples/sample.wav` が自動的に使用されます。

## 📦 機能概要

```mermaid
flowchart LR
    A[原稿CSV入力] --> B[音声生成<br/>output/temp]
    B --> C[音声再生]
    A --> D[原稿CSV出力]
    E[録音ボタン] --> F[sample.wav保存]
```

### 主要機能

| 機能 | 説明 |
|------|------|
| **原稿CSV入力** | inputフォルダにCSVファイルを上書き保存 |
| **録音** | マイクから音声サンプル（sample.wav）を録音 |
| **音声生成** | Coqui TTS（XTTS v2）でAI音声を生成、output/tempに音声を保存 |
| **音声再生** | 生成された音声を再生 |
| **原稿CSV出力** | 編集した原稿をCSVでダウンロード |

## 🚀 クイックスタート

### 1. 環境準備

```bash
# Python 3.10.11で仮想環境を作成
py -3.10 -m venv .venv
.venv\Scripts\activate

# 依存パッケージをインストール
pip install -r requirements.txt
```

### 2. ワンクリック起動

```powershell
# start.ps1を右クリック→「PowerShellで実行」、または
powershell -ExecutionPolicy Bypass -File start.ps1
```

### 3. 手動でサーバー起動

```bash
py -3.10 -m uvicorn src.server:app --host 127.0.0.1 --port 8000
```

### 4. ブラウザでアクセス

```
http://127.0.0.1:8000
```

### 5. 音声生成手順

1. **原稿CSV読み込み**: 「原稿CSV入力」でCSVを読み込み、input/原稿.csvに上書き保存
2. **音声サンプル録音（初回のみ）**: 「録音」でマイクから3-600秒の音声を録音（録音時間は手動設定可能）
3. **音声生成**: 「音声生成」でoutput/tempをクリアし音声ファイル（slide_000.mp3等）を生成
4. **音声再生**: 「音声再生」で生成された音声を確認
5. **原稿CSV出力**: 編集した原稿をCSVでダウンロード可能

### CLIで直接実行

```bash
# 音声サンプル録音
py -3.10 src\voice\create_voice.py

# 音声生成テスト
py -3.10 src\voice\voice_generator.py
```

## 📁 ファイル構成

```
MyVoice-Maker/
├── index.html          # WebアプリUI（GitHub Pages静的配信対応）
├── start.ps1           # ワンクリック起動スクリプト
├── requirements.txt    # Python依存パッケージ
├── pytest.ini          # pytest設定
├── input/
│   └── 原稿.csv        # ナレーション原稿
├── output/
│   └── temp/           # 音声ファイル（slide_000.mp3等）
├── src/
│   ├── main.py         # CLIエントリポイント（非推奨）
│   ├── processor.py    # 音声生成処理
│   ├── server.py       # FastAPIサーバー
│   └── voice/
│       ├── create_voice.py      # 音声サンプル録音
│       ├── voice_generator.py   # 音声生成クラス
│       └── models/samples/      # 音声サンプル保存先
├── tests/
│   └── e2e/            # E2Eテスト
├── docs/               # ドキュメント
└── specs/              # 仕様書
```

## 📝 原稿CSV形式

```csv
index,script
0,"最初のスライドの原稿テキストをここに記載します。"
1,"2番目のスライドの原稿です。複数行も可能です。"
2,"3番目のスライドの原稿。"
```

- **index**: スライド番号（0から開始）
- **script**: 読み上げ原稿テキスト
- **文字コード**: UTF-8（BOM付き推奨）、Shift_JIS、EUC-JP対応

## ⚙️ 環境変数設定

音声生成のパラメータを環境変数で調整できます：

| 変数名 | デフォルト | 説明 |
|--------|-----------|------|
| `USE_COQUI_TTS` | `1` | Coqui TTS使用（`0`で音声生成無効） |
| `COQUI_SPEAKER_WAV` | `src/voice/models/samples/sample.wav` | Coqui TTSの話者サンプル音声パス |

## ✅ テスト

```bash
# E2Eテスト
py -3.10 -m pytest -m e2e -v

# バックエンドE2Eテスト
py -3.10 -m pytest tests/e2e/test_local_backend.py -v
```

## � トラブルシューティング

### 文字化けする場合

原稿CSVをUTF-8（BOM付き）で保存してください。メモ帳の場合：
- 「名前を付けて保存」→ 文字コード: `UTF-8 (BOM付き)`

### FFmpegエラー

imageio-ffmpegが自動でFFmpegをダウンロードしますが、問題がある場合：

```bash
pip install --upgrade imageio-ffmpeg
```

### 音声が生成されない / タイムアウトエラー

**初回実行時の注意**: Coqui TTS (XTTS v2)モデルのダウンロードとロードに2-3分かかります。

**症状**: 「音声生成失敗: タイムアウト」エラー

**対策**:
1. **サーバーが起動しているか確認**:
   ```powershell
   # ポート8000を確認
   netstat -ano | findstr :8000
   
   # サーバーヘルスチェック
   Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/health"
   ```

2. **初回は10分程度待つ**: モデルダウンロードとロードに時間がかかります
   - ブラウザのコンソール（F12）で進捗を確認できます
   - `[fetchJson] リクエスト開始` と表示されていれば処理中です

3. **音声サンプルファイルを確認**:
   ```bash
   # ファイルが存在するか確認
   Test-Path src\voice\models\samples\sample.wav
   
   # 存在しない場合は録音
   py -3.10 src\voice\create_voice.py
   ```

4. **サーバーを再起動**:
   ```powershell
   # start.ps1で再起動
   powershell -ExecutionPolicy Bypass -File start.ps1
   ```

### バックエンドが検出されない

サーバーを起動してください：

```powershell
# ワンクリック起動
powershell -ExecutionPolicy Bypass -File start.ps1

# または手動起動
py -3.10 -m uvicorn src.server:app --host 127.0.0.1 --port 8000
```

## 📚 ドキュメント

| ドキュメント | 説明 |
|-------------|------|
| [完全仕様書](https://github.com/J1921604/MyVoice-Maker/blob/main/docs/完全仕様書.md) | 詳細な機能仕様 |
| [spec.md](https://github.com/J1921604/MyVoice-Maker/blob/main/specs/001-MyVoice-Maker/spec.md) | 機能仕様書 |
| [plan.md](https://github.com/J1921604/MyVoice-Maker/blob/main/specs/001-MyVoice-Maker/plan.md) | 実装計画 |
| [tasks.md](https://github.com/J1921604/MyVoice-Maker/blob/main/specs/001-MyVoice-Maker/tasks.md) | タスク一覧 |

## 🌐 GitHub Pages（静的UI）

Actionsが `dist` をデプロイし、静的な `index.html` をGitHub Pagesで公開します。バックエンドAPIはローカルサーバー（`start.ps1` / `py -3.10 -m uvicorn src.server:app`）で動かしてください。

手動でPages用アーティファクトを作る場合:

```bash
mkdir -p dist
cp index.html dist/
cp -r docs dist/docs
cp -r specs dist/specs
cp README.md dist/README.md
```

その後、`actions/upload-pages-artifact` と `actions/deploy-pages` で公開されます（`.github/workflows/pages.yml` 参照）。

## 📄 ライセンス

MIT License

## 🙏 クレジット

- [Coqui TTS](https://github.com/coqui-ai/TTS) - オープンソース音声合成（XTTS v2モデル使用）
- [FastAPI](https://fastapi.tiangolo.com/) - Webフレームワーク
