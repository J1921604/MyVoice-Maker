import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

from src.voice.voice_generator import VoiceGenerator, pick_default_speaker_wav

repo = Path.cwd()
speaker = pick_default_speaker_wav(repo / "src" / "voice" / "models" / "samples")
print(f"speaker: {speaker}")

if not speaker or not speaker.exists():
    print("ERROR: No speaker sample found")
    sys.exit(1)

# Check if it's fake mode
vg = VoiceGenerator()
print(f"_fake_tts: {vg._fake_tts}")

if vg._fake_tts:
    print("Running in FAKE TTS mode - generates silent audio")
else:
    print("Running in REAL TTS mode - will use Coqui XTTS v2")

# Generate a test file
out = repo / "output"
p = vg.generate_one(index=999, script="これはテスト音声です。", speaker_wav=speaker, output_dir=out, overwrite=True)
print(f"Generated: {p}")
print(f"Size: {p.stat().st_size} bytes")
