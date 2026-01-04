# CLI契約: MyVoice Maker

**日付**: 2026-01-05
**対象**: src/main.py

## コマンドライン引数

### 基本構文

```bash
py -3.10 src/main.py [オプション]
```

### 引数定義

| 引数 | 短縮形 | 型 | デフォルト | 説明 |
|------|--------|-----|-----------|------|
| `--script` | - | string | `input/原稿.csv` | 原稿CSVファイルパス |
| `--output` | - | string | `output/` | 生成MP3の出力ディレクトリ |
| `--speaker-wav` | - | string | 自動選択 | 話者サンプルWAV（未指定時は `src/voice/models/samples/` の最新 `sample_XX.wav` を使用） |
| `--no-overwrite` | - | flag | False | 既存の `output/slide_XXX.mp3` を上書きしない |

### 使用例

```bash
# デフォルト設定
py -3.10 src/main.py

# 出力先を変更
py -3.10 src/main.py --output .\\output

# 話者サンプルを明示指定
py -3.10 src/main.py --speaker-wav .\\src\\voice\\models\\samples\\sample_01.wav

# 既存ファイルを上書きしない
py -3.10 src/main.py --no-overwrite
```

## 終了コード

| コード | 意味 |
|--------|------|
| 0 | 正常終了 |
| 1 | 入力ファイルエラー |
| 2 | 処理エラー |

## 標準出力

### 正常時

```
生成完了: 12 件
```

### エラー時

```
Script CSV file not found: input/原稿.csv
Please create input\原稿.csv (columns: index, script).
```

## 環境変数（処理時に設定）

CLIは環境変数を必須としない。
