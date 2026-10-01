"""Objective facts about each move, so the narrator can check the models' reasoning.

Everything here comes from python-chess (and optionally a UCI engine), never from an LLM.
"""

from __future__ import annotations

from pathlib import Path

import chess
import chess.engine

from .episode import Episode

VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}


def material(board: chess.Board) -> int:
    """Material balance in pawns, from White's point of view."""
    total = 0
    for piece_type, value in VALUES.items():
        total += value * len(board.pieces(piece_type, chess.WHITE))
        total -= value * len(board.pieces(piece_type, chess.BLACK))
    return total


def hanging_pieces(board: chess.Board, color: chess.Color) -> list[str]:
    """Pieces of `color` that the side to move can win right now (cheap heuristic).

    A piece counts as hanging when it is attacked and either undefended or attacked
    by something cheaper. Kings and pawns are ignored.
    """
    out = []
    for sq, piece in board.piece_map().items():
        if piece.color != color or piece.piece_type in (chess.KING, chess.PAWN):
            continue
        attackers = board.attackers(not color, sq)
        if not attackers:
            continue
        defenders = board.attackers(color, sq)
        cheapest = min(VALUES.get(board.piece_type_at(a), 99) for a in attackers)
        if not defenders or cheapest < VALUES[piece.piece_type]:
            by = ", ".join(
                f"{board.piece_at(a).symbol().upper()}{chess.square_name(a)}" for a in attackers
            )
            out.append(f"{piece.symbol().upper()}{chess.square_name(sq)} (attacked by {by})")
    return out


def annotate(episode: Episode, engine_path: str | Path | None = None, depth: int = 14) -> None:
    """Fill move.facts in place."""
    engine = None
    if engine_path:
        engine = chess.engine.SimpleEngine.popen_uci(str(engine_path))
    try:
        prev_eval = None
        if engine:
            prev_eval = _eval(engine, chess.Board(episode.moves[0].fen_before), depth)
        for mv in episode.moves:
            before = chess.Board(mv.fen_before)
            move = chess.Move.from_uci(mv.uci)
            facts: dict = {
                "capture": before.is_capture(move),
                "captured": None,
            }
            if facts["capture"]:
                victim = before.piece_at(move.to_square) or chess.Piece(chess.PAWN, not before.turn)
                facts["captured"] = chess.piece_name(victim.piece_type)
            after = chess.Board(mv.fen_after)
            mover = before.turn
            facts.update(
                check=after.is_check(),
                checkmate=after.is_checkmate(),
                stalemate=after.is_stalemate(),
                material_white=material(after),
                hanging_after_move=hanging_pieces(after, mover),
                legal_replies=after.legal_moves.count(),
            )
            if engine:
                ev = _eval(engine, after, depth)
                facts["eval_white_cp"] = ev
                if prev_eval is not None and ev is not None:
                    swing = (ev - prev_eval) * (1 if mover == chess.WHITE else -1)
                    facts["eval_change_for_mover_cp"] = swing
                    if swing <= -300:
                        facts["engine_verdict"] = "blunder"
                    elif swing <= -120:
                        facts["engine_verdict"] = "mistake"
                prev_eval = ev
            mv.facts = facts
    finally:
        if engine:
            engine.quit()


def _eval(engine, board: chess.Board, depth: int) -> int | None:
    if board.is_game_over():
        if board.is_checkmate():
            return -10000 if board.turn == chess.WHITE else 10000
        return 0
    info = engine.analyse(board, chess.engine.Limit(depth=depth))
    return info["score"].white().score(mate_score=10000)
