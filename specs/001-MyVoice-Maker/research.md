# 調査結果: Slide MyVoice Maker

**日付**: 2026-1-5
**Phase**: 0 - 調査

## 調査概要

本ドキュメントは、Slide MyVoice Makerの解像度選択機能およびtemp上書き機能の実装に必要な技術調査結果をまとめたものである。

## 調査項目

### 1. 解像度指定方式の決定

**決定**: 環境変数 `OUTPUT_MAX_WIDTH` を使用

**根拠**:
- 既存の `processor.py` が `_get_output_max_width()` で環境変数を参照している
- 新規インターフェース追加より既存パターンの活用が保守性向上に寄与
- CLI引数から環境変数への変換は `main.py` で一元管理可能

**代替案と却下理由**:

| 代替案 | 却下理由 |
|--------|----------|
| 関数引数で直接渡す | processor.py全体の変更が必要になり影響範囲が大きい |
| 設定ファイル（JSON/YAML） | ワンクリック実行の簡便さが損なわれる |
| グローバル変数 | テスタビリティが低下する |

---

### 2. tempフォルダ削除方式の決定

**決定**: `shutil.rmtree()` を使用

**根拠**:
- Python標準ライブラリであり追加依存なし
- ディレクトリを再帰的に削除可能
- クロスプラットフォーム対応

**エラーハンドリング**:

```python
try:
    shutil.rmtree(temp_dir)
except PermissionError:
    # ファイルロック時は警告ログを出力して続行
    print(f"Warning: Could not clear temp folder: {e}")
```

**代替案と却下理由**:

| 代替案 | 却下理由 |
|--------|----------|
| os.remove() + os.rmdir() | ファイル単位で削除が必要で複雑 |
| pathlib.Path.unlink() | ディレクトリ対応が不十分 |
| subprocess + rm/rd | クロスプラットフォーム対応が複雑 |

---

### 3. UI解像度選択の実装方式

**決定**: React state + select要素

**根拠**:
- 既存の `index.html` がReact（Babel）を使用している
- 他のUI要素（ボイス選択など）と同じパターンで統一性確保
- Tailwind CSSでスタイリング済み

**実装パターン**:

```javascript
const [selectedResolution, setSelectedResolution] = useState('720p');
const RESOLUTION_OPTIONS = [
    { label: '720p (1280x720)', value: '720p', width: 1280, height: 720 },
    { label: '1080p (1920x1080)', value: '1080p', width: 1920, height: 1080 },
    { label: '1440p (2560x1440)', value: '1440p', width: 2560, height: 1440 },
];
```

---

### 4. 解像度とアスペクト比

**決定**: 16:9アスペクト比を採用

**解像度マッピング**:

| 選択肢 | 幅 | 高さ | アスペクト比 |
|--------|-----|------|--------------|
| 720p   | 1280 | 720 | 16:9 |
| 1080p  | 1920 | 1080 | 16:9 |
| 1440p  | 2560 | 1440 | 16:9 |

**根拠**:
- PDFスライドは通常16:9または4:3
- 16:9が動画配信プラットフォーム（YouTube等）の標準
- 4:3スライドは自動レターボックス処理で対応

---

### 5. エンコード設定の解像度対応

**調査結果**: 既存のVP8/VP9設定で解像度変更に対応可能

**関連環境変数**:

| 変数 | デフォルト | 高解像度推奨 |
|------|-----------|--------------|
| `USE_VP8` | 1 | 0（VP9推奨） |
| `VP9_CPU_USED` | 8 | 4-6 |
| `VP9_CRF` | 40 | 30-35 |
| `OUTPUT_FPS` | 15 | 15（据え置き） |

**注意**: 1440pではVP9使用を推奨（VP8は2560幅で品質低下）

---

## 技術スタック確認

### Python版

| 項目 | バージョン | 役割 |
|------|-----------|------|
| Python | 3.10.11 | ランタイム |
| edge-tts | 最新 | 音声合成 |
| moviepy | <2.0 | 動画編集 |
| pymupdf | 最新 | PDF処理 |
| pandas | 最新 | CSV読み込み |
| imageio-ffmpeg | 最新 | FFmpegラッパー |

### Web UI

| 項目 | バージョン | 役割 |
|------|-----------|------|
| React | 18 | UIフレームワーク |
| Babel | 最新 | JSXトランスパイル |
| Tailwind CSS | 3 | スタイリング |
| PDF.js | 3.11 | PDF表示 |
| Lucide Icons | 最新 | アイコン |

---

## 未解決事項

なし（すべての調査項目が解決済み）

---

## 参考リンク

- [MoviePy ドキュメント](https://zulko.github.io/moviepy/)
- [Edge TTS GitHub](https://github.com/rany2/edge-tts)
- [FFmpeg VP9 ガイド](https://trac.ffmpeg.org/wiki/Encode/VP9)
- [Python shutil ドキュメント](https://docs.python.org/3/library/shutil.html)
