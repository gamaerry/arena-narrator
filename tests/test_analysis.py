import pytest

from arena_narrator.spoken import san_to_words


def test_from_to_and_check(ep):
    nf6 = ep.moves[40]  # 21. Nf6+
    assert nf6.san == "Nf6+"
    assert (nf6.from_sq, nf6.to_sq) == ("e4", "f6")
    assert nf6.facts["check"] is True


def test_hanging_rook_detected(ep):
    # 21. Nf6+ ignored that the rook on d4 was attacked by the knight on c6
    assert any(h.startswith("Rd4") for h in ep.moves[40].facts["hanging_after_move"])


def test_final_mate_and_material(ep):
    assert ep.moves[-1].facts["checkmate"] is True
    assert ep.moves[-1].facts["material_white"] < -10


@pytest.mark.parametrize(
    "san, lang, words",
    [
        ("Nf3", "es", "caballo a efe tres"),
        ("exd5", "es", "peón e por de cinco"),
        ("Qg2#", "es", "dama a ge dos, jaque mate"),
        ("O-O", "es", "enroque corto"),
        ("a1=Q", "es", "peón a uno corona dama"),
        ("Nfd7", "en", "knight f to d seven"),
        ("Qa5+", "en", "queen to a five, check"),
    ],
)
def test_spoken(san, lang, words):
    assert san_to_words(san, lang) == words
