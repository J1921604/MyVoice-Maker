import sounddevice as sd
from scipy.io.wavfile import write
import numpy as np
import os

# 保存先パス（プロジェクト内の src/voice 配下へ）
SAVE_PATH = os.path.join('src', 'voice', 'models', 'samples', 'sample.wav')

# サンプリングレート
SAMPLE_RATE = 44100

if __name__ == '__main__':
    duration = input('録音する秒数を入力してください: ')
    try:
        duration = float(duration)
    except ValueError:
        print('数字を入力してください')
        exit(1)
    print('録音開始...')
    recording = sd.rec(int(duration * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype='int16')
    sd.wait()
    print('録音終了。保存中...')
    # 出力ディレクトリが存在しない場合は作成
    out_dir = os.path.dirname(SAVE_PATH)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    try:
        write(SAVE_PATH, SAMPLE_RATE, recording)
        print(f'保存しました: {SAVE_PATH}')
    except Exception as e:
        print(f'保存中にエラーが発生しました: {e}')
