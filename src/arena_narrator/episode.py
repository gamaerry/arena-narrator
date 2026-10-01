"""Download Kaggle Game Arena episodes and turn them into a list of moves."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import chess
import httpx

EPISODE_URL = "https://www.kaggleusercontent.com/episodes/{id}.json"


class EpisodeError(RuntimeError):
    pass


@dataclass
class Move:
    ply: int  # 1-based half-move index
    number: int  # full-move number as shown in PGN
    side: str  # "white" | "black"
    player: str  # team / model name
    san: str
    uci: str
    from_sq: str
    to_sq: str
    fen_before: str
    fen_after: str
    thoughts: str = ""
    time_taken: float | None = None
    # Filled in by analysis.annotate()
    facts: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Episode:
    id: int
    white: str
    black: str
    result: str  # "1-0" | "0-1" | "1/2-1/2" | "*"
    termination: str
    moves: list[Move]
    url: str
    # Set when a model lost by submitting an illegal/unparseable move
    forfeit: dict | None = None

    def player(self, side: str) -> str:
        return self.white if side == "white" else self.black


def parse_episode_id(value: str | int) -> int:
    """Accept a bare id, a kaggleusercontent URL or a game-arena URL with ?episodeId=."""
    s = str(value).strip()
    if s.isdigit():
        return int(s)
    m = re.search(r"episodeId=(\d+)", s) or re.search(r"episodes/(\d+)", s)
    if not m:
        raise EpisodeError(f"Could not find an episode id in {value!r}")
    return int(m.group(1))


def fetch(episode_id: int, out_dir: Path, *, refresh: bool = False) -> Path:
    """Download the raw episode JSON to out_dir/episode.json (cached)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "episode.json"
    if path.exists() and not refresh:
        return path
    url = EPISODE_URL.format(id=episode_id)
    r = httpx.get(url, follow_redirects=True, timeout=60)
    if r.status_code != 200 or not r.text.lstrip().startswith("{"):
        raise EpisodeError(f"Episode {episode_id} not available at {url} (HTTP {r.status_code})")
    path.write_text(r.text, encoding="utf-8")
    return path


def _fen_key(fen: str) -> str:
    # placement, side to move, castling, en passant; ignore move clocks
    return " ".join(fen.split()[:4])


def load(path: Path) -> Episode:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    game = raw.get("configuration", {}).get("openSpielGameName")
    if game != "chess":
        raise EpisodeError(f"Only chess episodes are supported (this one is {game!r})")
    if raw.get("configuration", {}).get("openSpielGameParameters", {}).get("chess960"):
        raise EpisodeError("Chess960 episodes are not supported yet")

    info = raw.get("info", {})
    teams: list[str] = info.get("TeamNames") or [a["Name"] for a in info.get("Agents", [])]
    states: list[str] = info.get("stateHistory") or []

    board = chess.Board(states[0]) if states else chess.Board()
    moves: list[Move] = []
    side_to_agent: dict[str, int] = {}
    forfeit: dict | None = None

    for step in raw["steps"]:
        for agent_idx, entry in enumerate(step):
            action = entry.get("action") or {}
            san_str = action.get("actionString")
            status = str(action.get("status") or "")
            if san_str and "forfeit" in status.lower():
                side = "white" if board.turn == chess.WHITE else "black"
                forfeit = {
                    "side": side,
                    "player": teams[agent_idx] if agent_idx < len(teams) else side,
                    "attempted": san_str,
                    "reason": status,
                    "thoughts": (action.get("thoughts") or "").strip(),
                    "after_ply": len(moves),
                }
                continue
            if not san_str or (entry.get("info") or {}).get("actionApplied") is None:
                continue
            side = "white" if board.turn == chess.WHITE else "black"
            side_to_agent.setdefault(side, agent_idx)
            fen_before = board.fen()
            try:
                mv = board.parse_san(san_str)
            except ValueError as e:
                raise EpisodeError(f"Illegal SAN {san_str!r} at ply {len(moves) + 1}") from e
            san = board.san(mv)
            board.push(mv)
            ply = len(moves) + 1
            if ply < len(states) and _fen_key(states[ply]) != _fen_key(board.fen()):
                raise EpisodeError(f"Board diverged from stateHistory at ply {ply}")
            moves.append(
                Move(
                    ply=ply,
                    number=(ply + 1) // 2,
                    side=side,
                    player=teams[agent_idx] if agent_idx < len(teams) else f"agent{agent_idx}",
                    san=san,
                    uci=mv.uci(),
                    from_sq=chess.square_name(mv.from_square),
                    to_sq=chess.square_name(mv.to_square),
                    fen_before=fen_before,
                    fen_after=board.fen(),
                    thoughts=(action.get("thoughts") or "").strip(),
                    time_taken=(entry.get("info") or {}).get("timeTaken"),
                )
            )

    if not moves:
        raise EpisodeError("Episode contains no moves")

    white_idx = side_to_agent.get("white", 0)
    black_idx = side_to_agent.get("black", 1 - white_idx)
    white = teams[white_idx] if white_idx < len(teams) else "White"
    black = teams[black_idx] if black_idx < len(teams) else "Black"

    rewards = raw.get("rewards") or []
    result, termination = "*", "unknown"
    if len(rewards) >= 2 and None not in rewards:
        rw, rb = rewards[white_idx], rewards[black_idx]
        result = "1-0" if rw > rb else "0-1" if rb > rw else "1/2-1/2"
    outcome = board.outcome(claim_draw=True)
    if outcome is not None:
        termination = outcome.termination.name.lower()
    elif result in ("1-0", "0-1"):
        termination = "forfeit"  # illegal move, timeout or resignation by the harness
    elif result == "1/2-1/2":
        termination = "draw"

    return Episode(
        id=int(info.get("EpisodeId") or 0),
        white=white,
        black=black,
        result=result,
        termination=termination,
        moves=moves,
        url=EPISODE_URL.format(id=info.get("EpisodeId")),
        forfeit=forfeit,
    )
