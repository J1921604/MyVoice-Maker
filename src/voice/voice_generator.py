import os
from pathlib import Path
from TTS.api import TTS
import torch
import platform
import subprocess

# TorchCodec問題回避: torchaudioの代わりにsoundfileを使うようにパッチ
def _patch_torchaudio_load():
    """torchaudio.loadをsoundfileベースに置き換えてTorchCodecを回避"""
    try:
        import soundfile as sf
        import torchaudio
        import numpy as np
        
        original_load = torchaudio.load
        
        def patched_load(filepath, *args, **kwargs):
            # soundfileで読み込み
            audio_data, sample_rate = sf.read(filepath)
            
            # numpy配列をtorch tensorに変換
            if audio_data.ndim == 1:
                audio_tensor = torch.from_numpy(audio_data).unsqueeze(0)  # (1, samples)
            else:
                audio_tensor = torch.from_numpy(audio_data.T)  # (channels, samples)
            
            return audio_tensor.float(), sample_rate
        
        # torchaudio.loadを置き換え
        torchaudio.load = patched_load
        print("TorchCodecバイパス: torchaudio.loadをsoundfileベースにパッチしました")
    except ImportError as e:
        print(f"Warning: soundfileのインポートに失敗。TorchCodecエラーが発生する可能性があります: {e}")

class Voice:
    def __init__(self):
        print("音声モデルを初期化中...")
        
        # TorchCodec回避パッチを適用
        _patch_torchaudio_load()
        
        device = "cuda" if torch.cuda.is_available() else "cpu"

        self.tts = TTS(
            model_name="tts_models/multilingual/multi-dataset/xtts_v2"
        ).to(device)

        # リポジトリルートを基準にパスを決定
        repo_root = Path(__file__).resolve().parents[2]

        # 複数候補からサンプルWAVを探す（プロジェクト内の場所が変更されている場合に対応）
        candidate_wavs = [
            repo_root / "src" / "voice" / "models" / "samples" / "sample.wav",
        ]
        found = None
        for p in candidate_wavs:
            if p.exists():
                found = str(p)
                break

        if found:
            self.speaker_wav = found
        else:
            # 見つからなければ None にして TTS のデフォルト合成を利用
            self.speaker_wav = None
            print("Warning: speaker sample not found; using default voice. Searched:")
            for p in candidate_wavs:
                print(f"  - {p}")

        # 出力はリポジトリルートの output に揃える
        out_dir = repo_root / "output"
        out_dir.mkdir(parents=True, exist_ok=True)
        print("初期化完了！")

    def speak(self, text, output_filename="output.wav"):
        repo_root = Path(__file__).resolve().parents[2]
        output_path = repo_root / "output" / output_filename
        
        print(f"音声生成中: {text}")
        
        if not self.speaker_wav:
            raise ValueError("speaker_wavが設定されていません。create_voice.pyでサンプル音声を録音してください。")
        
        print(f"speaker_wavを使用: {self.speaker_wav}")
        
        # Coqui TTS（XTTS v2）で音声生成
        self.tts.tts_to_file(
            text=text,
            speaker_wav=str(self.speaker_wav),
            language="ja",
            file_path=str(output_path)
        )
        print(f"生成完了: {output_path}")
        return output_path

    def test_voice(self):
        test_text = "こんにちは、お母さん。今日も元気ですか？"
        output_file = self.speak(test_text, "test_voice.wav")

        if output_file:
            print(f"テスト音声を生成しました: {output_file}")
            # クロスプラットフォームで再生
            try:
                plat = platform.system()
                if plat == "Darwin":
                    subprocess.run(["afplay", str(output_file)])
                elif plat == "Windows":
                    # powershell の Start-Process を直接呼ぶ方法もあるが subprocess で start を利用
                    subprocess.run(["powershell", "-c", f"(New-Object Media.SoundPlayer '{output_file}').PlaySync();"]) 
                else:
                    # Linux: aplay または paplay
                    played = False
                    for cmd in (["paplay", str(output_file)], ["aplay", str(output_file)]):
                        try:
                            subprocess.run(cmd, check=True)
                            played = True
                            break
                        except Exception:
                            continue
                    if not played:
                        print("再生コマンドが見つかりません（paplay/aplay）。ファイルを手動で再生してください。")
            except Exception as e:
                print(f"再生中にエラー: {e}")  

        return output_file

if __name__ == "__main__":
    voice = Voice()
    voice.test_voice()
    voice.speak("お薬の時間です", "medicine_time.wav")
    voice.speak("今日は良い天気ですね", "good_weather.wav")
