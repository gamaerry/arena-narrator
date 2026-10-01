"""Text-to-speech backends. Each one turns a text into an audio file and reports its duration."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Protocol

DEFAULT_VOICES = {
    "edge": {"es": "es-MX-JorgeNeural", "en": "en-US-GuyNeural"},
    "piper": {"es": "es_MX-ald-medium", "en": "en_US-lessac-medium"},
}


class TTSError(RuntimeError):
    pass


class TTS(Protocol):
    name: str
    ext: str
    voice: str

    def synth_many(self, jobs: list[tuple[str, Path]]) -> None:
        """Write each (text, path) job. Paths already include the extension."""


def get_tts(name: str, lang: str, voice: str | None = None, rate: str | None = None) -> TTS:
    voice = voice or DEFAULT_VOICES[name][lang]
    if name == "edge":
        from .edge import EdgeTTS

        return EdgeTTS(voice, rate=rate)
    if name == "piper":
        from .piper import PiperTTS

        return PiperTTS(voice, rate=rate)
    raise TTSError(f"Unknown TTS {name!r}; choose edge or piper")


def text_hash(text: str, voice: str, rate: str | None) -> str:
    return hashlib.sha1(f"{voice}|{rate}|{text}".encode()).hexdigest()[:10]


def duration(path: Path) -> float:
    from mutagen import File as MutagenFile

    audio = MutagenFile(path)
    if audio is None or not getattr(audio, "info", None):
        raise TTSError(f"Cannot read duration of {path}")
    return round(float(audio.info.length), 3)


def voice_segments(segments: list[dict], tts: TTS, audio_dir: Path) -> None:
    """Synthesize every segment (skipping cached files) and set seg['audio'/'duration']."""
    audio_dir.mkdir(parents=True, exist_ok=True)
    jobs = []
    for i, seg in enumerate(segments):
        name = f"{i:03d}-{text_hash(seg['text'], tts.voice, getattr(tts, 'rate', None))}.{tts.ext}"
        path = audio_dir / name
        seg["_path"] = path
        if not path.exists() or path.stat().st_size == 0:
            jobs.append((seg["text"], path))
    if jobs:
        print(f"  synthesizing {len(jobs)}/{len(segments)} clips with {tts.name}:{tts.voice} …",
              file=sys.stderr)
        tts.synth_many(jobs)
    for seg in segments:
        path = seg.pop("_path")
        seg["audio"] = path
        seg["duration"] = duration(path)


def concat(paths: list[Path], out: Path) -> Path | None:
    """Join clips into a single file with ffmpeg (returns None if ffmpeg is missing)."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in paths), encoding="utf-8")
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst)]
    if out.suffix == paths[0].suffix:
        cmd += ["-c", "copy"]
    cmd.append(str(out))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    lst.unlink(missing_ok=True)
    if proc.returncode != 0:
        print(f"  ffmpeg concat failed: {proc.stderr.strip()}", file=sys.stderr)
        return None
    return out
