"""Microsoft Edge online voices via edge-tts (free, needs internet)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from . import TTSError


class EdgeTTS:
    name = "edge"
    ext = "mp3"

    def __init__(self, voice: str, rate: str | None = None, concurrency: int = 4):
        try:
            import edge_tts  # noqa: F401
        except ImportError as e:
            raise TTSError("pip install 'arena-narrator[edge]'") from e
        self.voice = voice
        self.rate = rate
        self.concurrency = concurrency

    def synth_many(self, jobs: list[tuple[str, Path]]) -> None:
        asyncio.run(self._run(jobs))

    async def _run(self, jobs: list[tuple[str, Path]]) -> None:
        import edge_tts

        sem = asyncio.Semaphore(self.concurrency)

        async def one(text: str, path: Path) -> None:
            kwargs = {"rate": self.rate} if self.rate else {}
            async with sem:
                for attempt in range(3):
                    try:
                        tmp = path.with_suffix(".part")
                        await edge_tts.Communicate(text, voice=self.voice, **kwargs).save(str(tmp))
                        tmp.replace(path)
                        return
                    except Exception:
                        if attempt == 2:
                            raise
                        await asyncio.sleep(2 * (attempt + 1))

        await asyncio.gather(*(one(t, p) for t, p in jobs))
