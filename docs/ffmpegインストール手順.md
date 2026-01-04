# FFmpeg インストール手順（Windows）

## 概要

MyVoice Makerでは、音声生成にFFmpegを使用します。Coqui TTS（XTTS v2）による音声生成では、soundfileライブラリを使用して音声処理を実装しています。

## 前提条件

- Windows 10/11
- Python 3.10.11
- 7-Zip がインストール済み（winget でインストール可能）

## インストール手順

### 1. FFmpegのダウンロード

公式ビルドサイトから最新のFFmpegをダウンロードします：

**ダウンロード元**: https://www.gyan.dev/ffmpeg/builds/

- `ffmpeg-*-git-*-full_build.7z` または `ffmpeg-*-essentials_build.7z` を選択
- 例: `ffmpeg-2025-12-31-git-38e89fe502-full_build.7z`

### 2. 7-Zipのインストール（未インストールの場合）

PowerShellで以下を実行：

```powershell
winget install -e --id 7zip.7zip
```

### 3. FFmpegの展開

ダウンロードしたファイルをC:\ffmpegに展開します：

```powershell
# ダウンロードファイルのパス（適宜変更）
$zip = 'C:\Users\ユーザー名\Downloads\ffmpeg-2025-12-31-git-38e89fe502-full_build.7z'

# C:\ffmpegに展開
& 'C:\Program Files\7-Zip\7z.exe' x $zip -oC:\ffmpeg -y
```

### 4. 展開後のフォルダ構造確認

展開後、以下のような構造になります：

```
C:\ffmpeg\
 ffmpeg-YYYY-MM-DD-git-xxxxxx-full_build\
     bin\
        ffmpeg.exe
        ffplay.exe
        ffprobe.exe
        その他のDLLファイル
     doc\
     presets\
```

### 5. ffmpeg.exeの場所を確認

```powershell
# ffmpeg.exeを検索
Get-ChildItem 'C:\ffmpeg' -Recurse -Filter ffmpeg.exe | Select-Object FullName
```

出力例：

```
FullName
--------
C:\ffmpeg\ffmpeg-2025-12-31-git-38e89fe502-full_build\bin\ffmpeg.exe
```

### 6. PATH環境変数への追加

#### 6-1. 現在のPowerShellセッションで一時的に有効化

```powershell
# 見つかったbinフォルダのパスを設定（上記の出力から取得）
$ffbin = 'C:\ffmpeg\ffmpeg-2025-12-31-git-38e89fe502-full_build\bin'

# 現在のセッションのPATHに追加
$env:PATH += ";$ffbin"

# 動作確認
ffmpeg -version
```

#### 6-2. ユーザー環境変数に恒久的に追加

```powershell
# ユーザー環境変数のPATHに追加（既存のPATHを上書きしない）
[Environment]::SetEnvironmentVariable(
    'PATH',
    [Environment]::GetEnvironmentVariable('PATH','User') + ";$ffbin",
    'User'
)
```

**注意**: 環境変数の変更は新しいPowerShellウィンドウで有効になります。現在のウィンドウでは上記の `$env:PATH +=` で一時的に使えます。

### 7. インストール確認

新しいPowerShellウィンドウを開いて確認：

```powershell
ffmpeg -version
```

以下のような出力が表示されれば成功です：

```
ffmpeg version 2025-12-31-git-38e89fe502-full_build-www.gyan.dev
Copyright (c) 2000-2025 the FFmpeg developers
built with gcc 15.2.0 (Rev8, Built by MSYS2 project)
configuration: --enable-gpl --enable-version3 --enable-static ...
libavutil      60. 21.102 / 60. 21.102
libavcodec     62. 23.102 / 62. 23.102
libavformat    62.  8.102 / 62.  8.102
...
```

## 動作確認

音声生成スクリプトを実行して、Coqui TTSが正常に動作するか確認：

```powershell
# プロジェクトディレクトリに移動
cd C:\Users\ユーザー名\spec-kit\12_MyVoice-Maker

# 仮想環境を有効化（.venvがある場合）
.\.venv\Scripts\Activate.ps1

# 音声サンプルを作る（推奨: Web UI の「録音」）
# 既存の音声ファイルを sample_XX.wav に変換して追加する場合:
py -3.10 src\voice\create_voice.py --input path\to\recording.webm
```

成功時の出力例：

```
Coqui TTS モデルを初期化中... (device: cpu)
初回実行時はモデルダウンロードに30-60秒かかります。
音声生成中: こんにちは、お元気ですか。
speaker_wavを読み込みました: ...\sample.wav
生成完了: ...\output\test_voice.wav
```

## トラブルシューティング

### エラー: "ffmpeg が認識されません"

**原因**: FFmpegのパスが通っていない

**対処法**:

1. `ffmpeg -version` が動作するか確認
2. 新しいPowerShellウィンドウで再試行（環境変数の反映）
3. システム再起動後に再試行

### エラー: "Could not find ffmpeg"

**原因**: imageio-ffmpegがFFmpegを検出できない

**対処法**:

1. PATH環境変数が正しく設定されているか確認
2. ffmpeg.exeがbinフォルダに存在するか確認：
   ```powershell
   Test-Path 'C:\ffmpeg\...\bin\ffmpeg.exe'
   ```
3. imageio-ffmpegを再インストール：
   ```powershell
   pip install --force-reinstall imageio-ffmpeg
   ```

## 参考リンク

- [FFmpeg公式サイト](https://www.ffmpeg.org/)
- [Gyan.dev FFmpeg Builds](https://www.gyan.dev/ffmpeg/builds/)
- [Coqui TTS公式ドキュメント](https://github.com/coqui-ai/TTS)
- [soundfile公式ドキュメント](https://github.com/bastibe/python-soundfile)
