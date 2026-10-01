"""arena-narrator command line."""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import socket
import sys
import threading
import webbrowser
from pathlib import Path

from . import __version__, analysis, episode, manifest, narrate, terminal
from .llm import PROVIDERS, LLMError, get_llm
from .tts import DEFAULT_VOICES, TTSError, concat, get_tts, voice_segments


def _out_dir(args, ep_id: int) -> Path:
    return Path(args.out) / str(ep_id)


def _resolve_dir(target: str, out: str) -> Path:
    """`view`/`play` accept either an output directory or an episode id/URL."""
    p = Path(target)
    if p.is_dir():
        return p
    return Path(out) / str(episode.parse_episode_id(target))


def _load_episode(args) -> tuple[episode.Episode, Path]:
    ep_id = episode.parse_episode_id(args.episode)
    out = _out_dir(args, ep_id)
    path = episode.fetch(ep_id, out, refresh=getattr(args, "refresh", False))
    ep = episode.load(path)
    analysis.annotate(ep, engine_path=getattr(args, "engine", None))
    return ep, out


def cmd_fetch(args) -> None:
    ep, out = _load_episode(args)
    print(f"Episode {ep.id}: {ep.white} (white) vs {ep.black} (black) → {ep.result}, "
          f"{ep.termination}, {len(ep.moves)} plies")
    print(f"Saved to {out / 'episode.json'}")
    if args.moves:
        for mv in ep.moves:
            dots = "." if mv.side == "white" else "..."
            hang = f"  ⚠ hanging: {', '.join(mv.facts['hanging_after_move'])}" \
                if mv.facts.get("hanging_after_move") else ""
            print(f"{mv.number:>3}{dots:<3} {mv.san:<8} {mv.player}{hang}")


def _script(args, ep, out) -> dict:
    llm = get_llm(args.provider, args.model)
    return narrate.make_script(ep, llm, args.lang, out, chunk_size=args.chunk, regen=args.regen)


def cmd_script(args) -> None:
    ep, out = _load_episode(args)
    script = _script(args, ep, out)
    print(f"Script: {out / f'script.{args.lang}.json'} ({len(script['segments'])} segments)")


def cmd_build(args) -> None:
    ep, out = _load_episode(args)
    print(f"Episode {ep.id}: {ep.white} vs {ep.black} ({ep.result}, {len(ep.moves)} plies)",
          file=sys.stderr)
    script = _script(args, ep, out)

    tts = get_tts(args.tts, args.lang, args.voice, args.rate)
    segments = [dict(s) for s in script["segments"]]
    voice_segments(segments, tts, out / "audio" / args.lang / args.tts)
    script = {**script, "segments": segments}

    full = None
    if not args.no_concat:
        full = concat([s["audio"] for s in segments], out / f"narration.{args.lang}.mp3")
    path = manifest.build(ep, script, out, tts=tts.name, voice=tts.voice, full_audio=full)
    total = sum(s["duration"] for s in segments)
    print(f"Done: {path} · {len(segments)} clips · {total / 60:.1f} min of audio")
    if full:
        print(f"Full narration: {full}")
    print(f"Watch it:  arena-narrator view {out}   ·   arena-narrator play {out}")


def _free_port(preferred: int) -> int:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]


def cmd_view(args) -> None:
    out = _resolve_dir(args.target, args.out)
    if not (out / "index.json").exists():
        sys.exit(f"No manifest in {out}; run `arena-narrator build` first.")
    manifest.install_viewer(out)  # refresh viewer files from the installed version
    port = _free_port(args.port)
    handler = functools.partial(_QuietHandler, directory=str(out))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    url = f"http://127.0.0.1:{port}/"
    if args.lang:
        url += f"?lang={args.lang}"
    print(f"Serving {out} at {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a) -> None:
        pass


def cmd_play(args) -> None:
    out = _resolve_dir(args.target, args.out)
    data = manifest.load(out, args.lang)
    terminal.play(data, out, audio=not args.no_audio, start_ply=args.from_ply, flip=args.flip)


def cmd_voices(args) -> None:
    print(json.dumps(DEFAULT_VOICES, indent=2))
    print("\nedge: `edge-tts --list-voices`  ·  piper: `python -m piper.download_voices`")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="arena-narrator",
        description="Narrate Kaggle Game Arena chess episodes around each model's reasoning.",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--out", default="out", help="output root directory (default: ./out)")
    sub = p.add_subparsers(dest="cmd", required=True)

    def episode_args(sp):
        sp.add_argument("episode", help="episode id or Kaggle URL (…?episodeId=123)")
        sp.add_argument("--refresh", action="store_true", help="re-download the episode")
        sp.add_argument("--engine", help="path to a UCI engine (e.g. stockfish) for extra facts")

    def script_args(sp):
        sp.add_argument("--lang", choices=["es", "en"], default="es")
        sp.add_argument("--provider", choices=["auto", *PROVIDERS], default="auto",
                        help="LLM that writes the narration (default: auto-detect)")
        sp.add_argument("--model", help="override the provider's default model")
        sp.add_argument("--chunk", type=int, default=30, help="plies per LLM call (default 30)")
        sp.add_argument("--regen", action="store_true", help="ignore the cached script")

    sp = sub.add_parser("fetch", help="download an episode and print a summary")
    episode_args(sp)
    sp.add_argument("--moves", action="store_true", help="list moves and hanging pieces")
    sp.set_defaults(func=cmd_fetch)

    sp = sub.add_parser("script", help="write the narration script only")
    episode_args(sp)
    script_args(sp)
    sp.set_defaults(func=cmd_script)

    sp = sub.add_parser("build", help="fetch + script + audio + viewer (everything)")
    episode_args(sp)
    script_args(sp)
    sp.add_argument("--tts", choices=["edge", "piper"], default="edge")
    sp.add_argument("--voice", help="TTS voice (see `arena-narrator voices`)")
    sp.add_argument("--rate", help='speech rate, e.g. "+10%%" or "-5%%"')
    sp.add_argument("--no-concat", action="store_true", help="skip the single narration file")
    sp.set_defaults(func=cmd_build)

    sp = sub.add_parser("view", help="open the HTML viewer in the browser")
    sp.add_argument("target", help="output directory or episode id")
    sp.add_argument("--lang", help="language to open first")
    sp.add_argument("--port", type=int, default=8765)
    sp.add_argument("--no-browser", action="store_true")
    sp.set_defaults(func=cmd_view)

    sp = sub.add_parser("play", help="play in the terminal (ANSI board + audio)")
    sp.add_argument("target", help="output directory or episode id")
    sp.add_argument("--lang")
    sp.add_argument("--no-audio", action="store_true", help="silent, timed by clip length")
    sp.add_argument("--from-ply", type=int, default=0, help="start at this ply")
    sp.add_argument("--flip", action="store_true", help="show the board from Black's side")
    sp.set_defaults(func=cmd_play)

    sp = sub.add_parser("voices", help="show default voices")
    sp.set_defaults(func=cmd_voices)
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except (episode.EpisodeError, LLMError, TTSError) as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
