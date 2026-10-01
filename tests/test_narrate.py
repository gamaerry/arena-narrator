import json

from arena_narrator import manifest, narrate


class FakeLLM:
    name, model = "fake", "fake-1"

    def __init__(self, skip_ply=None):
        self.calls = []
        self.skip_ply = skip_ply

    def complete_json(self, system, user, schema):
        self.calls.append(user)
        plies = [int(line.split()[2].rstrip(":")) for line in user.splitlines()
                 if line.startswith("--- ply")]
        return {
            "intro": "Hola" if "Write an INTRO" in user else "",
            "outro": "Adiós" if "Write an OUTRO" in user else "",
            "summary": f"through ply {plies[-1]}",
            "segments": [{"ply": p, "text": f"jugada {p}"} for p in plies if p != self.skip_ply],
        }


def test_script_covers_every_ply(ep, tmp_path):
    llm = FakeLLM()
    script = narrate.make_script(ep, llm, "es", tmp_path, chunk_size=30)
    assert len(llm.calls) == 4  # 100 plies / 30
    segs = script["segments"]
    assert segs[0] == {"kind": "intro", "ply": 0, "text": "Hola"}
    assert segs[-1]["kind"] == "outro"
    assert [s["ply"] for s in segs if s["kind"] == "move"] == list(range(1, 101))
    assert "through ply 30" in llm.calls[1]  # running summary is passed on
    # cached on second call
    narrate.make_script(ep, llm, "es", tmp_path)
    assert len(llm.calls) == 4


def test_missing_ply_gets_fallback(ep, tmp_path):
    script = narrate.make_script(ep, FakeLLM(skip_ply=41), "es", tmp_path)
    seg = next(s for s in script["segments"] if s["ply"] == 41 and s["kind"] == "move")
    assert "caballo a efe seis" in seg["text"]


def test_prompt_contains_reasoning_and_spoken(ep):
    prompt = narrate.build_prompt(ep, ep.moves[40:42], "es", "", False, False)
    assert "spoken: caballo a efe seis, jaque" in prompt
    assert "Rd4" in prompt
    assert ep.moves[40].thoughts.splitlines()[0] in prompt


def test_manifest(ep, tmp_path):
    script = narrate.make_script(ep, FakeLLM(), "es", tmp_path)
    for i, seg in enumerate(script["segments"]):
        seg["audio"] = tmp_path / "audio" / f"{i:03d}.mp3"
        seg["duration"] = 1.5
    path = manifest.build(ep, script, tmp_path, tts="edge", voice="v", full_audio=None)
    data = json.loads(path.read_text())
    assert data["white"] == "gpt-6-astra" and data["result"] == "0-1"
    assert data["segments"][1]["audio"] == "audio/001.mp3"
    assert data["moves"][-1]["san"] == "Qg2#"
    assert json.loads((tmp_path / "index.json").read_text()) == {"langs": ["es"]}
    assert (tmp_path / "index.html").exists() and (tmp_path / "viewer.js").exists()
