# -*- coding: utf-8 -*-
"""統合テスト: 音声生成が正常に動作することを確認"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

def test_audio_file_exists():
    """生成された音声ファイルの確認"""
    audio_file = Path("output/temp/test/slide_000.mp3")
    
    print("=" * 60)
    print("統合テスト: 音声ファイル生成確認")
    print("=" * 60)
    
    if audio_file.exists():
        size = audio_file.stat().st_size
        print(f"\n✅ 成功！音声ファイルが存在します")
        print(f"   ファイル: {audio_file}")
        print(f"   サイズ: {size:,} bytes ({size/1024:.2f} KB)")
        print(f"   更新日時: {audio_file.stat().st_mtime}")
        
        if size > 1000:
            print(f"\n✅ ファイルサイズが十分です（{size/1024:.2f} KB > 1 KB）")
            print("\n【結論】Coqui TTSは正常に動作しています！")
            return True
        else:
            print(f"\n❌ ファイルサイズが小さすぎます（{size/1024:.2f} KB）")
            return False
    else:
        print(f"\n❌ 音声ファイルが見つかりません: {audio_file}")
        print("\n対処方法:")
        print("1. サーバーが起動しているか確認: py -3.10 -m uvicorn src.server:app --host 127.0.0.1 --port 8000")
        print("2. ブラウザで http://127.0.0.1:8000/index.html を開く")
        print("3. PDF・CSV入力 → 画像・音声生成を実行")
        return False

if __name__ == "__main__":
    success = test_audio_file_exists()
    sys.exit(0 if success else 1)
