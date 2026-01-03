import os
import asyncio
import glob
import argparse

from processor import process_pdf_and_script, clear_temp_folder

# 解像度マッピング
RESOLUTION_MAP = {
    "720": 1280,
    "720p": 1280,
    "1080": 1920,
    "1080p": 1920,
    "1440": 2560,
    "1440p": 2560,
}

async def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    parser = argparse.ArgumentParser(
        description="Generate narrated videos (webm) from PDF pages + narration script CSV.",
    )
    parser.add_argument(
        "--input",
        default=os.path.join(base_dir, "input"),
        help="Input directory containing PDF file(s).",
    )
    parser.add_argument(
        "--output",
        default=os.path.join(base_dir, "output"),
        help="Output directory for generated webm files.",
    )
    parser.add_argument(
        "--script",
        default=os.path.join(base_dir, "input", "原稿.csv"),
        help="Narration script CSV path (default: input\\原稿.csv).",
    )
    parser.add_argument(
        "--resolution",
        default="720",
        choices=["720", "720p", "1080", "1080p", "1440", "1440p"],
        help="Output video resolution (default: 720p). Options: 720/720p, 1080/1080p, 1440/1440p.",
    )
    args = parser.parse_args()

    input_dir = args.input
    output_dir = args.output
    script_csv_path = args.script
    
    # 解像度設定を環境変数にセット
    resolution_width = RESOLUTION_MAP.get(args.resolution, 1280)
    os.environ["OUTPUT_MAX_WIDTH"] = str(resolution_width)
    print(f"Output resolution: {resolution_width}px width ({args.resolution})")

    os.makedirs(output_dir, exist_ok=True)

    if not os.path.exists(script_csv_path):
        print(f"Script CSV file not found: {script_csv_path}")
        print("Please create input\\原稿.csv (columns: index, script).")
        return

    pdf_files = glob.glob(os.path.join(input_dir, "*.pdf"))
    if not pdf_files:
        print(f"No PDF files found in input directory: {input_dir}")
        return

    for pdf_path in pdf_files:
        # temp上書き: 処理前にtempフォルダをクリア
        base_name = os.path.splitext(os.path.basename(pdf_path))[0]
        temp_dir = os.path.join(output_dir, "temp", base_name)
        clear_temp_folder(temp_dir)
        
        await process_pdf_and_script(pdf_path, script_csv_path, output_dir)

if __name__ == "__main__":
    asyncio.run(main())
