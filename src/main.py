from __future__ import annotations

import argparse
import sys
from pathlib import Path


# `python src/main.py ...` で実行されるケース（e2e含む）では、sys.path[0] が src/ になり
# `import src...` が解決できない。リポジトリルートを明示的に追加して安定させる。
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.voice.voice_generator import get_voice_generator, pick_default_speaker_wav


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]

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

    if args.speaker_wav:
        speaker = Path(args.speaker_wav)
    else:
        speaker = pick_default_speaker_wav()

    if speaker is None or not speaker.exists():
        print("Speaker sample not found.")
        print("Place sample_01.wav etc under src\\voice\\models\\samples.")
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
            output_dir=out_dir,
            overwrite=not args.no_overwrite,
        )
        print(f"生成完了: {out_path}")
    else:
        generated = vg.generate_from_csv(
            script_csv_path=script_csv,
            speaker_wav=speaker,
            output_dir=out_dir,
            overwrite=not args.no_overwrite,
        )
        print(f"生成完了: {len(generated)} 件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
