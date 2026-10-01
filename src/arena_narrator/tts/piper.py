"""Local, offline voices via Piper (piper-tts). Voices are downloaded on first use."""

from __future__ import annotations

import os
import subprocess
import sys
import wave
from pathlib import Path

from . import TTSError

CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "arena-narrator" / "piper"


class PiperTTS:
    name = "piper"
    ext = "wav"

    def __init__(self, voice: str, rate: str | None = None):
        try:
            from piper import PiperVoice  # noqa: F401
        except ImportError as e:
            raise TTSError("pip install 'arena-narrator[piper]'") from e
        self.voice = voice
        self.rate = rate
        self._model = None

    def _model_path(self) -> Path:
        if self.voice.endswith(".onnx"):
            return Path(self.voice)
        path = CACHE / f"{self.voice}.onnx"
        if not path.exists():
            CACHE.mkdir(parents=True, exist_ok=True)
            print(f"  downloading Piper voice {self.voice} …", file=sys.stderr)
            cmd = [sys.executable, "-m", "piper.download_voices", self.voice,
                   "--data-dir", str(CACHE)]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0 or not path.exists():
                raise TTSError(f"Could not download Piper voice {self.voice}: {proc.stderr[-500:]}")
        return path

    def _load(self):
        if self._model is None:
            from piper import PiperVoice

            self._model = PiperVoice.load(str(self._model_path()))
        return self._model

    def _syn_config(self):
        if not self.rate:
            return None
        from piper import SynthesisConfig

        # rate like "+10%" → faster speech → shorter phoneme length
        pct = float(self.rate.strip("%")) / 100
        return SynthesisConfig(length_scale=1 / (1 + pct))

    def synth_many(self, jobs: list[tuple[str, Path]]) -> None:
        model = self._load()
        cfg = self._syn_config()
        for text, path in jobs:
            tmp = path.with_suffix(".part")
            with wave.open(str(tmp), "wb") as wav:
                if cfg is None:
                    model.synthesize_wav(text, wav)
                else:
                    model.synthesize_wav(text, wav, syn_config=cfg)
            tmp.replace(path)
