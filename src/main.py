from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# `python src/main.py ...` で実行されるケース（e2e含む）では、sys.path[0] が src/ になり
# `import src...` が解決できない。リポジトリルートを明示的に追加して安定させる。
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.voice.voice_generator import get_voice_generator, pick_default_speaker_wav


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _voice_model_json_path(repo_root: Path) -> Path:
    return repo_root / "src" / "voice" / "models" / "tts_model.json"


def _abs_from_repo(repo_root: Path, s: str) -> Path:
    p = Path(s)
    return p if p.is_absolute() else (repo_root / p).resolve()


def _load_saved_voice_model(repo_root: Path) -> dict:
    p = _voice_model_json_path(repo_root)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def main() -> int:
    repo_root = _repo_root()

    parser = argparse.ArgumentParser(
        description="Generate MP3 narration from input/原稿.csv using Coqui XTTS v2.",
    )
    parser.add_argument(
        "--script",
        default=str(repo_root / "input" / "原稿.csv"),
        help="Narration script CSV path (default: input\\原稿.csv).",
    )
    parser.add_argument(
        "--output",
        default=str(repo_root / "output"),
        help="Output directory for generated mp3 files.",
    )
    parser.add_argument(
        "--speaker-wav",
        default="",
        help="Speaker WAV path (default: auto from src/voice/models/samples).",
    )
    parser.add_argument(
        "--index",
        type=int,
        default=None,
        help="Generate only the specified index from the CSV (default: generate all rows).",
    )
    parser.add_argument(
        "--no-overwrite",
        action="store_true",
        help="Do not overwrite existing output files.",
    )
    args = parser.parse_args()

    script_csv = Path(args.script)
    out_dir = Path(args.output)

    if not script_csv.exists():
        print(f"Script CSV file not found: {script_csv}")
        print("Please create input\\原稿.csv (columns: index, script).")
        return 2

    # 可能なら、事前構築済み voice キャッシュ（埋め込み）を優先して利用する。
    # これにより speaker_wav からの埋め込み再計算を回避できる。
    voice_id = None
    voice_dir = None
    speaker = None

    if args.speaker_wav:
        # 明示指定は最優先（キャッシュより上）
        speaker = Path(args.speaker_wav)
    else:
        saved = _load_saved_voice_model(repo_root)
        if saved.get("voice_id") and saved.get("voice_dir"):
            voice_id = str(saved.get("voice_id"))
            voice_dir = _abs_from_repo(repo_root, str(saved.get("voice_dir")))
            voice_file = voice_dir / f"{voice_id}.pth"
            if not voice_file.exists():
                voice_id = None
                voice_dir = None

        if voice_id is None and saved.get("speaker_wav"):
            speaker = _abs_from_repo(repo_root, str(saved.get("speaker_wav")))

        if voice_id is None and (speaker is None or not speaker.exists()):
            speaker = pick_default_speaker_wav()

    if voice_id is None:
        if speaker is None or not speaker.exists():
            print("Speaker sample not found.")
            print("Place sample_01.wav etc under src\\voice\\models\\samples.")
            print("Or build voice cache from the Web UI (音声生成モデル構築).")
            return 2

    vg = get_voice_generator()
    if args.index is not None:
        # まず CSV を読み、指定indexの行だけ生成する。
        # VoiceGenerator は公開APIとして load_script_csv を持たないため、モジュール関数を使う。
        from src.voice.voice_generator import load_script_csv

        rows = load_script_csv(script_csv)

        target = next((r for r in rows if r.index == args.index), None)
        if target is None:
            print(f"Index not found in CSV: {args.index}")
            return 2
        if not target.script.strip():
            print(f"Script is empty for index: {args.index}")
            return 2

        out_path = vg.generate_one(
            index=target.index,
            script=target.script,
            speaker_wav=speaker,
            voice_id=voice_id,
            voice_dir=voice_dir,
            output_dir=out_dir,
            overwrite=not args.no_overwrite,
        )
        print(f"生成完了: {out_path}")
    else:
        generated = vg.generate_from_csv(
            script_csv_path=script_csv,
            speaker_wav=speaker,
            voice_id=voice_id,
            voice_dir=voice_dir,
            output_dir=out_dir,
            overwrite=not args.no_overwrite,
        )
        print(f"生成完了: {len(generated)} 件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
