from pathlib import Path

import pytest

from arena_narrator import analysis, episode

FIXTURE = Path(__file__).parent / "fixtures" / "episode_109084577.json"


@pytest.fixture
def ep():
    e = episode.load(FIXTURE)
    analysis.annotate(e)
    return e
