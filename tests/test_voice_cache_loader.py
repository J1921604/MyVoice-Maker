from __future__ import annotations

import torch

from src.voice.voice_generator import _load_voice_file


class _Dummy:
    def __init__(self, value: int):
        self.value = value


def test_load_voice_file_allows_pickle_objects(tmp_path):
    """weights_only=False で .pth を読み込めることを確認する."""

    voice_file = tmp_path / "voice.pth"
    payload = {
        "gpt_conditioning_latents": torch.ones((1, 4)),
        "speaker_embedding": torch.ones((1, 3)) * 2,
        "custom": _Dummy(7),
    }
    torch.save(payload, voice_file)

    loaded = _load_voice_file(voice_file, map_location="cpu")

    assert isinstance(loaded, dict)
    assert "gpt_conditioning_latents" in loaded
    assert "speaker_embedding" in loaded
    assert isinstance(loaded.get("custom"), _Dummy)
    assert loaded["custom"].value == 7
