"""Write the manifest that both viewers read, and install the HTML viewer."""

from __future__ import annotations

import json
import shutil
from importlib import resources
from pathlib import Path

from .episode import Episode

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def build(episode: Episode, script: dict, out_dir: Path, *, tts: str, voice: str,
          full_audio: Path | None) -> Path:
    moves = [
        {
            "ply": m.ply,
            "number": m.number,
            "side": m.side,
            "player": m.player,
            "san": m.san,
            "from": m.from_sq,
            "to": m.to_sq,
            "fen": m.fen_after,
            "thoughts": m.thoughts,
            "time": m.time_taken,
            "check": bool(m.facts.get("check")),
        }
        for m in episode.moves
    ]
    segments = [
        {
            "kind": s["kind"],
            "ply": s["ply"],
            "text": s["text"],
            "audio": Path(s["audio"]).relative_to(out_dir).as_posix() if s.get("audio") else None,
            "duration": s.get("duration"),
        }
        for s in script["segments"]
    ]
    lang = script["lang"]
    data = {
        "episode": episode.id,
        "source": f"https://www.kaggle.com/game-arena?episodeId={episode.id}",
        "white": episode.white,
        "black": episode.black,
        "result": episode.result,
        "termination": episode.termination,
        "forfeit": episode.forfeit,
        "start_fen": episode.moves[0].fen_before if episode.moves else START_FEN,
        "lang": lang,
        "tts": tts,
        "voice": voice,
        "narrator": f"{script.get('provider')}:{script.get('model')}",
        "full_audio": full_audio.relative_to(out_dir).as_posix() if full_audio else None,
        "moves": moves,
        "segments": segments,
    }
    path = out_dir / f"manifest.{lang}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    index_path = out_dir / "index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {"langs": []}
    if lang not in index["langs"]:
        index["langs"].append(lang)
    index_path.write_text(json.dumps(index), encoding="utf-8")

    install_viewer(out_dir)
    return path


def install_viewer(out_dir: Path) -> None:
    src = resources.files("arena_narrator") / "viewer"
    for name in ("index.html", "viewer.js", "viewer.css"):
        with resources.as_file(src / name) as p:
            shutil.copyfile(p, out_dir / name)


def load(out_dir: Path, lang: str | None = None) -> dict:
    if lang is None:
        index = json.loads((out_dir / "index.json").read_text())
        lang = index["langs"][0]
    return json.loads((out_dir / f"manifest.{lang}.json").read_text(encoding="utf-8"))
