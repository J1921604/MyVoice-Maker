# -*- coding: utf-8 -*-
"""Coqui TTS動作確認スクリプト"""
import os
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent))

# processor.pyのgenerate_voice関数をテスト
import asyncio
from src.processor import generate_voice

async def test_voice_generation():
    """音声生成の動作確認"""
    print("=" * 60)
    print("Coqui TTS 動作確認テスト開始")
    print("=" * 60)
    
    # テストテキスト
    test_text = "こんにちは。これはテスト音声です。"
    
    # 出力パス
    output_path = "output/test_voice.mp3"
    os.makedirs("output", exist_ok=True)
    
    try:
        print(f"\nテキスト: {test_text}")
        print(f"出力先: {output_path}")
        print("\n音声生成中...")
        
        # 音声生成実行
        await generate_voice(test_text, output_path)
        
        # 結果確認
        if os.path.exists(output_path):
            size = os.path.getsize(output_path)
            print(f"\n✅ 成功！音声ファイルが生成されました")
            print(f"   ファイルサイズ: {size:,} bytes")
            print(f"   保存先: {output_path}")
        else:
            print(f"\n❌ 失敗：音声ファイルが見つかりません")
            return False
            
    except FileNotFoundError as e:
        print(f"\n❌ エラー: 音声サンプルファイルが見つかりません")
        print(f"   {e}")
        print("\n対処方法:")
        print("   py -3.10 src\\voice\\create_voice.py を実行して音声サンプルを録音してください")
        return False
        
    except Exception as e:
        print(f"\n❌ エラー発生: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print("\n" + "=" * 60)
    print("テスト完了")
    print("=" * 60)
    return True

if __name__ == "__main__":
    success = asyncio.run(test_voice_generation())
    sys.exit(0 if success else 1)
