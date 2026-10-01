"""Build the narration script with an LLM, chunk by chunk."""

from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from .episode import Episode, Move
from .llm import LLM
from .spoken import san_to_words

LANG_NAMES = {"en": "English", "es": "Spanish (neutral Latin American)"}

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["intro", "segments", "outro", "summary"],
    "properties": {
        "intro": {"type": "string"},
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["ply", "text"],
                "properties": {"ply": {"type": "integer"}, "text": {"type": "string"}},
            },
        },
        "outro": {"type": "string"},
        "summary": {"type": "string"},
    },
}

SYSTEM = """\
You are a lively but rigorous chess commentator narrating a game played between two large \
language models in Kaggle Game Arena. The models play without an engine: before every move \
each one wrote down its reasoning, and that reasoning is the heart of your commentary.

Your text is read aloud by a text-to-speech engine, so:
- Write plain prose only: no markdown, bullet points, emojis, headings or stage directions.
- Never write algebraic notation (Nf3, exd5, O-O, +, #). Say every move with the spoken form \
provided for it (for example "knight to f three" / "caballo a efe tres"), and squares the same way.
- Use short sentences with varied rhythm, like a broadcaster.
- Write everything in {language}, translating or paraphrasing the models' reasoning (it is \
usually in English). You may quote a short, striking phrase.

For each move:
1. Say who plays what, using short and consistent names for the players (e.g. "Gemini", \
"Astra"; "las blancas"/"las negras" are fine too).
2. Tell the listener what the model said it was thinking: its plan, the lines it calculated, \
what it worried about. If a model wrote no reasoning, say so briefly or just narrate the move.
3. When the FACTS show a model missed something (it left a piece hanging, walked into a tactic \
that the next moves prove, contradicted itself, described an impossible line), point it out \
clearly. Only use the facts given (hanging pieces, material, checks, engine verdicts if any, \
and what actually happened next in the game score). Never invent engine evaluations or \
opening theory you are not sure about.

Length: a routine move gets one sentence (10-20 words). Turning points (material changes, \
hanging pieces, checks that lead somewhere, long thinking times, contradictions, the final \
blows) get two to five sentences.

Return exactly one segment per ply listed under MOVES TO NARRATE, in order, with "ply" set to \
that ply number. Fill "intro" only when asked to (otherwise ""), and "outro" only when asked \
to (otherwise ""). "summary" is two to four sentences in English summarizing the story of the \
game so far, for continuity in the next chunk.
"""


def _pgn(episode: Episode) -> str:
    parts = []
    for mv in episode.moves:
        if mv.side == "white":
            parts.append(f"{mv.number}. {mv.san}")
        elif mv.ply == 1:
            parts.append(f"{mv.number}... {mv.san}")
        else:
            parts.append(mv.san)
    return " ".join(parts) + f" {episode.result}"


def _move_block(mv: Move, lang: str) -> str:
    f = mv.facts or {}
    facts = []
    if f.get("capture"):
        facts.append(f"captures a {f.get('captured')}")
    if f.get("checkmate"):
        facts.append("CHECKMATE")
    elif f.get("check"):
        facts.append("check")
    if "material_white" in f:
        facts.append(
            f"material balance after move (White minus Black, pawns): {f['material_white']:+d}"
        )
    if f.get("hanging_after_move"):
        facts.append(
            "mover's pieces attacked and undefended/underdefended after the move (heuristic; "
            "check the actual continuation before calling it a mistake): "
            + "; ".join(f["hanging_after_move"])
        )
    if "eval_white_cp" in f:
        facts.append(f"engine eval (White POV, centipawns): {f['eval_white_cp']}")
    if f.get("engine_verdict"):
        facts.append(f"engine verdict: {f['engine_verdict']}")
    t = f"{mv.time_taken:.0f}s" if mv.time_taken else "?"
    dots = "." if mv.side == "white" else "..."
    return (
        f"--- ply {mv.ply}: {mv.number}{dots} {mv.san} by {mv.side} ({mv.player}), "
        f"thought for {t}\n"
        f"spoken: {san_to_words(mv.san, lang)}\n"
        f"facts: {'; '.join(facts) or 'none'}\n"
        f"model reasoning:\n{mv.thoughts or '(no reasoning recorded)'}\n"
    )


def build_prompt(episode: Episode, chunk: list[Move], lang: str, summary: str,
                 first: bool, last: bool) -> str:
    total = len(episode.moves)
    lines = [
        f"GAME: Kaggle Game Arena episode {episode.id}",
        f"White: {episode.white}",
        f"Black: {episode.black}",
        f"Result: {episode.result} ({episode.termination}), {total} plies",
        f"Full game score (for context only): {_pgn(episode)}",
        "",
        f"Story so far: {summary or '(this is the start of the game)'}",
        "",
    ]
    if first:
        lines.append("Write an INTRO (3-5 sentences): welcome the listener, present both "
                     "models and colours, and say that we will follow each model's reasoning. "
                     "Do not reveal the result.")
    if last and episode.forfeit:
        f = episode.forfeit
        lines.append(
            f"HOW IT ENDED: after the last move below, {f['player']} ({f['side']}) tried to play "
            f"{f['attempted']!r} (spoken: {san_to_words(f['attempted'], lang)}), which the "
            f"arena rejected: {f['reason']} That lost the game. Its reasoning for that "
            f"attempt was:\n{f['thoughts'] or '(none)'}\nExplain this in the OUTRO."
        )
    if last:
        lines.append("Write an OUTRO (4-7 sentences): the result, how it was decided, and what "
                     "the game showed about how each model reasons.")
    lines.append(f"\nMOVES TO NARRATE (plies {chunk[0].ply}-{chunk[-1].ply} of {total}):\n")
    lines.extend(_move_block(mv, lang) for mv in chunk)
    return "\n".join(lines)


TEMPLATES = {
    "en": {
        "intro": "Kaggle Game Arena. {white} has the white pieces, {black} the black pieces.",
        "outro": "Final result: {result}. {winner}",
        "forfeit": "{player} tried an illegal move, {move}, and forfeited the game.",
        "win": "{name} wins.",
        "draw": "The game is drawn.",
        "plays": "{player} plays {move}.",
    },
    "es": {
        "intro": "Kaggle Game Arena. {white} juega con blancas y {black} con negras.",
        "outro": "Resultado final: {result}. {winner}",
        "forfeit": "{player} intentó una jugada ilegal, {move}, y perdió por descalificación.",
        "win": "Gana {name}.",
        "draw": "La partida termina en tablas.",
        "plays": "{player} juega {move}.",
    },
}


SENTENCE_END = re.compile(r"(?<=[a-z)\]][.!?])\s+")
SAN_TOKEN = re.compile(r"\b(?:[KQRBN][a-h]?[1-8]?x?[a-h][1-8]|[a-h]x[a-h][1-8])(?:=[QRBN])?[+#]?")


def _first_sentence(text: str, lang: str = "en") -> str:
    text = " ".join(text.replace("*", "").replace("`", "").replace("$", "").split())
    text = text.split("Final Answer")[0].strip()
    first = SENTENCE_END.split(text, maxsplit=1)[0] if text else ""
    first = first if len(first) <= 240 else first[:240].rsplit(" ", 1)[0] + "…"
    # piece moves and captures inside the reasoning are read as words too
    return SAN_TOKEN.sub(lambda m: san_to_words(m.group(0), lang), first)


def _fallback_text(mv: Move, lang: str, with_reasoning: bool = False) -> str:
    text = TEMPLATES[lang]["plays"].format(player=mv.player, move=san_to_words(mv.san, lang))
    # The models reason in English, so only quote them when narrating in English.
    if with_reasoning and lang == "en" and mv.thoughts:
        first = _first_sentence(mv.thoughts)
        if first:
            text += f" Its reasoning: {first}"
    return text


def _template_bookends(episode: Episode, lang: str) -> tuple[str, str]:
    t = TEMPLATES[lang]
    intro = t["intro"].format(white=episode.white, black=episode.black)
    winner = {"1-0": episode.white, "0-1": episode.black}.get(episode.result)
    verdict = t["win"].format(name=winner) if winner else t["draw"]
    if episode.forfeit:
        f = episode.forfeit
        verdict = t["forfeit"].format(player=f["player"],
                                      move=san_to_words(f["attempted"], lang)) + " " + verdict
    result = episode.result.replace("-", " a " if lang == "es" else " to ")
    return intro, t["outro"].format(result=result, winner=verdict)


def make_script(episode: Episode, llm: LLM, lang: str, out_dir: Path, *,
                chunk_size: int = 30, regen: bool = False) -> dict:
    """Return the script dict, cached at out_dir/script.<lang>.json."""
    if lang not in LANG_NAMES:
        raise ValueError(f"Unsupported language {lang!r}")
    path = out_dir / f"script.{lang}.json"
    partial_path = out_dir / f"script.{lang}.partial.json"
    if path.exists() and not regen:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if cached.get("provider") == llm.name:
            return cached
        print(f"  cached script was made by {cached.get('provider')}; regenerating with "
              f"{llm.name}", file=sys.stderr)

    partial = {}
    if partial_path.exists() and not regen:
        partial = json.loads(partial_path.read_text(encoding="utf-8"))
        if partial.pop("_provider", None) != llm.name:
            partial = {}

    system = SYSTEM.format(language=LANG_NAMES[lang])
    moves = episode.moves
    chunks = [moves[i : i + chunk_size] for i in range(0, len(moves), chunk_size)]
    summary = ""
    intro = outro = ""
    by_ply: dict[int, str] = {}

    for idx, chunk in enumerate(chunks):
        key = f"{chunk[0].ply}-{chunk[-1].ply}"
        first, last = idx == 0, idx == len(chunks) - 1
        if key in partial:
            data = partial[key]
        else:
            print(f"  narrating plies {key} with {llm.name}:{llm.model} …", file=sys.stderr)
            prompt = build_prompt(episode, chunk, lang, summary, first, last)
            data = llm.complete_json(system, prompt, SCHEMA)
            partial[key] = data
            partial_path.write_text(
                json.dumps({"_provider": llm.name, **partial}, ensure_ascii=False, indent=1),
                "utf-8",
            )
        summary = data.get("summary", summary)
        if first:
            intro = data.get("intro", "").strip()
        if last:
            outro = data.get("outro", "").strip()
        wanted = {mv.ply for mv in chunk}
        for seg in data.get("segments", []):
            ply, text = seg.get("ply"), (seg.get("text") or "").strip()
            if ply in wanted and text:
                by_ply[ply] = f"{by_ply[ply]} {text}" if ply in by_ply else text

    template = llm.name == "none"
    if template:
        intro, outro = _template_bookends(episode, lang)

    segments = []
    if intro:
        segments.append({"kind": "intro", "ply": 0, "text": intro})
    missing = 0
    for mv in moves:
        text = by_ply.get(mv.ply)
        if not text:
            missing += not template
            text = _fallback_text(mv, lang, with_reasoning=template)
        segments.append({"kind": "move", "ply": mv.ply, "text": text})
    if outro:
        segments.append({"kind": "outro", "ply": moves[-1].ply, "text": outro})
    if missing:
        print(f"  warning: {missing} plies had no narration; used a plain fallback",
              file=sys.stderr)

    script = {
        "episode": episode.id,
        "lang": lang,
        "provider": llm.name,
        "model": llm.model,
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "segments": segments,
    }
    path.write_text(json.dumps(script, ensure_ascii=False, indent=1), encoding="utf-8")
    partial_path.unlink(missing_ok=True)
    return script
