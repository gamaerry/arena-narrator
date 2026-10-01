"""Minimal terminal player: ANSI board + subtitles + audio through mpv/ffplay/paplay."""

from __future__ import annotations

import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path

GLYPHS = {"k": "♚", "q": "♛", "r": "♜", "b": "♝", "n": "♞", "p": "♟"}
LIGHT, DARK = (240, 217, 181), (181, 136, 99)
HL_LIGHT, HL_DARK = (205, 210, 106), (170, 162, 58)
CHECK = (220, 80, 80)
WHITE_FG, BLACK_FG = (255, 255, 255), (20, 20, 20)
LABELS = {
    "en": {"white": "White", "black": "Black", "thinks": "thought for"},
    "es": {"white": "Blancas", "black": "Negras", "thinks": "pensó"},
}


def _bg(rgb):
    return f"\x1b[48;2;{rgb[0]};{rgb[1]};{rgb[2]}m"


def _fg(rgb):
    return f"\x1b[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m"


RESET = "\x1b[0m"


def render_board(fen: str, last: tuple[str, str] | None = None, check_side: str | None = None,
                 flip: bool = False) -> str:
    rows = []
    for r in fen.split()[0].split("/"):
        row = []
        for ch in r:
            row.extend([None] * int(ch)) if ch.isdigit() else row.append(ch)
        rows.append(row)
    ranks = list(range(8))
    files = list(range(8))
    if flip:
        ranks.reverse()
        files.reverse()
    lines = []
    for ri in ranks:
        rank_no = 8 - ri
        line = f" {rank_no} "
        for fi in files:
            sq = "abcdefgh"[fi] + str(rank_no)
            piece = rows[ri][fi]
            light = (ri + fi) % 2 == 0
            bg = LIGHT if light else DARK
            if last and sq in last:
                bg = HL_LIGHT if light else HL_DARK
            if piece and piece.lower() == "k" and check_side:
                if (piece == "K") == (check_side == "white"):
                    bg = CHECK
            cell = "   "
            if piece:
                fg = WHITE_FG if piece.isupper() else BLACK_FG
                cell = f"{_fg(fg)} {GLYPHS[piece.lower()]} "
            line += f"{_bg(bg)}{cell}{RESET}"
        lines.append(line)
    file_labels = "".join(f" {'abcdefgh'[f]} " for f in files)
    lines.append("   " + file_labels)
    return "\n".join(lines)


def _player_cmd(path: Path) -> list[str] | None:
    if shutil.which("mpv"):
        return ["mpv", "--no-video", "--really-quiet", str(path)]
    if shutil.which("ffplay"):
        return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)]
    if path.suffix == ".wav":
        for p in ("pw-play", "paplay", "aplay"):
            if shutil.which(p):
                return [p, str(path)]
    return None


def play(manifest: dict, out_dir: Path, *, audio: bool = True, start_ply: int = 0,
         flip: bool = False) -> None:
    lang = manifest.get("lang", "en")
    lab = LABELS.get(lang, LABELS["en"])
    moves = {m["ply"]: m for m in manifest["moves"]}
    width = min(shutil.get_terminal_size((100, 30)).columns, 100)
    if audio and manifest["segments"] and manifest["segments"][0].get("audio"):
        if _player_cmd(out_dir / manifest["segments"][0]["audio"]) is None:
            print("No audio player found (mpv, ffplay, pw-play); continuing silently.")
            audio = False

    header = f"♔ {manifest['white']}  vs  ♚ {manifest['black']}   ({manifest['result']})"
    try:
        for seg in manifest["segments"]:
            if seg["kind"] != "outro" and seg["ply"] < start_ply:
                continue
            mv = moves.get(seg["ply"])
            fen = mv["fen"] if mv else manifest["start_fen"]
            last = (mv["from"], mv["to"]) if mv else None
            check_side = None
            if mv and mv["check"]:
                check_side = "black" if mv["side"] == "white" else "white"
            sys.stdout.write("\x1b[2J\x1b[H")
            print(header + "\n")
            print(render_board(fen, last, check_side, flip))
            print()
            if mv:
                dots = "." if mv["side"] == "white" else "..."
                t = f" · {lab['thinks']} {mv['time']:.0f}s" if mv.get("time") else ""
                print(f"\x1b[1m{mv['number']}{dots} {mv['san']}\x1b[0m  "
                      f"{mv['player']} ({lab[mv['side']]}){t}\n")
            print(textwrap.fill(seg["text"], width=width))
            sys.stdout.flush()

            cmd = _player_cmd(out_dir / seg["audio"]) if audio and seg.get("audio") else None
            if cmd:
                subprocess.run(cmd, stdin=subprocess.DEVNULL)
            else:
                time.sleep(seg.get("duration") or max(2.0, len(seg["text"]) / 15))
    except KeyboardInterrupt:
        print(RESET + "\n")
