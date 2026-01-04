# 001-Slide-MyVoice-Maker

本フォルダは MyVoice Maker の「スライド生成・音声生成」運用に関する補足仕様（派生仕様）を置く。

## 反映済み改善点（2026-01-04）

### 1) 話者埋め込みキャッシュの確実利用

- PyTorch 2.6 以降の既定 `torch.load(weights_only=True)` により、XTTS の話者キャッシュ `.pth` がロードできず、
  **キャッシュが効かずに毎回再計算**されるケースがあった。
- 対策として、`.pth` は **`weights_only=False`** を明示してロードし、埋め込み（latents）をメモリ常駐させて再利用する。

期待効果:
- 2回目以降の生成で話者埋め込み再計算を回避し、生成開始までの待ちを短縮。

### 2) ログ保存と“止まり箇所”の可視化

- 生成が「処理中 0/20」等で止まる場合、原因が **モデルDL/初期化** なのか、**音声生成** なのかを切り分ける必要がある。
- そのため、初期化・生成APIの開始/終了/所要時間を `logs/app.log` に保存する。

追加仕様:
- `GET /api/tts_status` で初期化ステージ（stage/ready/message）を取得できる。
- `POST /api/generate_audio` はモデル初期化中に **202(warming)** を返す。
  - Web UI は 202 を受けたら「モデル初期化中: ...」を表示しながら待機し、同じ行を自動リトライする。

運用:
- まず `logs/app.log` を確認し、`[VoiceGenerator] init: loading XTTS model...` の後に進んでいるかを確認する。
- 次に `/api/generate_audio start ...` の後に `... done ...` が出るかを確認する。
