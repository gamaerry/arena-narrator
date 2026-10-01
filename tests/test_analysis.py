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


def test_win_chances_and_classify():
    from arena_narrator.analysis import classify, win_chances

    assert win_chances(0) == 0
    assert win_chances(5000) == win_chances(1000)  # clamped
    assert classify(0.44) == "blunder"
    assert classify(0.25) == "mistake"
    assert classify(0.15) == "inaccuracy"
    assert classify(0.05) is None


@pytest.mark.skipif(not __import__("shutil").which("stockfish"), reason="stockfish not installed")
def test_engine_flags_nf6(ep):
    import shutil

    from arena_narrator import analysis

    analysis.annotate(ep, engine_path=shutil.which("stockfish"), depth=12)
    f = ep.moves[40].facts
    assert "engine_verdict" in f  # exact label depends on depth / engine version
    assert "engine_best_move" in f
    # winning a queen while staying completely winning is not flagged
    assert "engine_verdict" not in ep.moves[59].facts
