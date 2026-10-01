"""Turn SAN into words a TTS engine can read aloud (English / Spanish)."""

from __future__ import annotations

import re

PIECES = {
    "en": {"K": "king", "Q": "queen", "R": "rook", "B": "bishop", "N": "knight", "P": "pawn"},
    "es": {"K": "rey", "Q": "dama", "R": "torre", "B": "alfil", "N": "caballo", "P": "peón"},
}
FILES = {
    "en": dict(zip("abcdefgh", "a b c d e f g h".split(), strict=True)),
    "es": dict(zip("abcdefgh", "a be ce de e efe ge hache".split(), strict=True)),
}
RANKS = {
    "en": "one two three four five six seven eight".split(),
    "es": "uno dos tres cuatro cinco seis siete ocho".split(),
}
WORDS = {
    "en": {
        "to": "to", "takes": "takes", "check": "check", "mate": "checkmate",
        "O-O": "castles kingside", "O-O-O": "castles queenside", "promotes": "promotes to",
    },
    "es": {
        "to": "a", "takes": "por", "check": "jaque", "mate": "jaque mate",
        "O-O": "enroque corto", "O-O-O": "enroque largo", "promotes": "corona",
    },
}

SAN_RE = re.compile(
    r"^(?P<piece>[KQRBN])?(?P<dis>[a-h]?[1-8]?)(?P<x>x)?(?P<to>[a-h][1-8])"
    r"(?:=(?P<promo>[QRBN]))?(?P<chk>[+#])?$"
)


def square(sq: str, lang: str) -> str:
    return f"{FILES[lang][sq[0]]} {RANKS[lang][int(sq[1]) - 1]}"


def san_to_words(san: str, lang: str = "en") -> str:
    w = WORDS[lang]
    core = san.rstrip("+#!?")
    suffix = ""
    if san.endswith("#"):
        suffix = f", {w['mate']}"
    elif "+" in san:
        suffix = f", {w['check']}"
    if core in ("O-O", "O-O-O"):
        return w[core] + suffix

    m = SAN_RE.match(core)
    if not m:
        return san
    piece = PIECES[lang][m["piece"] or "P"]
    parts = [piece]
    dis = m["dis"]
    if dis:
        parts.append(" ".join(FILES[lang][c] if c.isalpha() else RANKS[lang][int(c) - 1]
                              for c in dis))
    if m["x"]:
        parts.append(w["takes"])
    elif m["piece"]:
        parts.append(w["to"])
    parts.append(square(m["to"], lang))
    if m["promo"]:
        parts.append(f"{w['promotes']} {PIECES[lang][m['promo']]}")
    return " ".join(parts) + suffix
