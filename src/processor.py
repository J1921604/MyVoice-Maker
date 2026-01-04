"""旧来の処理モジュール（互換用スタブ）。

現在の MyVoice Maker は「原稿CSV → 音声（MP3）」に特化しており、処理本体は
`src/voice/voice_generator.py` と `src/server.py` に集約されています。

このファイルは、過去の環境で `src.processor` を参照しているケースがあっても
致命的に壊れないよう、最小限の関数だけを残したスタブです。
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path


def clear_temp_folder(temp_dir: str) -> bool:
    """一時フォルダを削除して作り直す。

    Windows のファイルロックを考慮し、軽いリトライを行う。
    """

    p = Path(temp_dir)
    try:
        if p.exists():
            last_perm: PermissionError | None = None
            for _ in range(3):
                try:
                    shutil.rmtree(p, ignore_errors=False)
                    break
                except PermissionError as e:
                    last_perm = e
                    time.sleep(0.3)

            if p.exists() and last_perm is not None:
                # どうしても消せない場合でも、以降の処理が進められるようにフォルダ作成は試す
                pass

        p.mkdir(parents=True, exist_ok=True)
        return True
    except Exception:
        try:
            p.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return False

