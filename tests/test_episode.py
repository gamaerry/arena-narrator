import pytest

from arena_narrator import episode


def test_players_and_result(ep):
    assert ep.white == "gpt-6-astra"
    assert ep.black == "gemini-3.7-flash"
    assert ep.result == "0-1"
    assert ep.termination == "checkmate"
    assert len(ep.moves) == 100


def test_moves(ep):
    first, last = ep.moves[0], ep.moves[-1]
    assert (first.san, first.side, first.player) == ("e4", "white", "gpt-6-astra")
    assert (last.san, last.side, last.number) == ("Qg2#", "black", 50)
    assert "Final Answer: e4" in first.thoughts
    assert first.time_taken == pytest.approx(8.075)


@pytest.mark.parametrize(
    "value, expected",
    [
        ("109084577", 109084577),
        ("https://www.kaggle.com/game-arena?benchmarkModelVersionId=164&episodeId=109084577",
         109084577),
        ("https://www.kaggleusercontent.com/episodes/42.json", 42),
    ],
)
def test_parse_episode_id(value, expected):
    assert episode.parse_episode_id(value) == expected


def test_parse_episode_id_rejects_garbage():
    with pytest.raises(episode.EpisodeError):
        episode.parse_episode_id("not an episode")


def test_no_forfeit_in_checkmate_game(ep):
    assert ep.forfeit is None
