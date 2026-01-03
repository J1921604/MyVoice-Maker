# CLI契約: Slide MyVoice Maker

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
| `--input` | - | string | `input/` | 入力ディレクトリパス |
| `--output` | - | string | `output/` | 出力ディレクトリパス |
| `--script` | - | string | `input/原稿.csv` | 原稿CSVファイルパス |
| `--resolution` | - | string | `720` | 出力解像度 |

### --resolution 有効値

| 値 | 出力幅 | 出力高さ |
|----|--------|----------|
| `720` | 1280 | 720 |
| `720p` | 1280 | 720 |
| `1080` | 1920 | 1080 |
| `1080p` | 1920 | 1080 |
| `1440` | 2560 | 1440 |
| `1440p` | 2560 | 1440 |

### 使用例

```bash
# デフォルト設定
py -3.10 src/main.py

# 1080p出力
py -3.10 src/main.py --resolution 1080p

# フルオプション
py -3.10 src/main.py \
  --input ./input \
  --output ./output \
  --script ./input/原稿.csv \
  --resolution 1440p
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
Output resolution: 1920px width (1080p)
Cleared temp folder: output/temp/プレゼン資料
Processing: プレゼン資料.pdf
...
Video saved: output/プレゼン資料.webm
```

### エラー時

```
Script CSV file not found: input/原稿.csv
Please create input\原稿.csv (columns: index, script).
```

## 環境変数（処理時に設定）

| 変数 | 設定タイミング | 値 |
|------|--------------|-----|
| `OUTPUT_MAX_WIDTH` | --resolution解析後 | 1280/1920/2560 |
