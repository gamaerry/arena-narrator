# arena-narrator

**Turn any [Kaggle Game Arena](https://www.kaggle.com/game-arena) chess episode into a narrated replay built around what each model was *thinking*.**

In Game Arena, LLMs play chess with no engine: before every move each model writes down its reasoning. `arena-narrator` downloads an episode and asks an LLM to write a broadcaster-style script in **English or Spanish**. The script follows that reasoning move by move, and it points out a model's mistake only when there are objective facts to back it up. It then voices the script with **edge-tts** (online, free) or **Piper** (offline). You watch the result in a tiny synced board viewer, either in the **browser** or in the **terminal**.

```
episode JSON ──► parse + python-chess facts ──► LLM script ──► TTS clips ──► manifest ──► viewer
 (Kaggle)          (SAN, FEN, checks,           (es / en,      (edge-tts      (JSON)      (HTML or
                    material, hanging pieces,     one segment     or Piper)                 terminal)
                    optional Stockfish)           per move)
```

## Quick start

```bash
git clone https://github.com/gamaerry/arena-narrator && cd arena-narrator
uv sync --extra edge --extra anthropic          # or: --extra piper / --extra gemini / --extra all

export ANTHROPIC_API_KEY=...                    # or OPENROUTER_API_KEY / GEMINI_API_KEY
uv run arena-narrator build 109084577 --lang es --tts edge
uv run arena-narrator view out/109084577        # browser
uv run arena-narrator play out/109084577        # terminal
```

The episode argument also accepts the URL straight from the site:
`"https://www.kaggle.com/game-arena?episodeId=109084577"`.

## Commands

| command | what it does |
|---|---|
| `fetch <episode> [--moves]` | download the episode and print a summary (plus a move list with hanging pieces) |
| `script <episode>` | write only the narration script (`script.<lang>.json`) |
| `build <episode>` | fetch + script + audio + manifest + viewer, i.e. everything |
| `view <dir\|episode>` | serve the HTML viewer on localhost and open it |
| `play <dir\|episode>` | ANSI board in the terminal, with audio through mpv / ffplay / pw-play |
| `voices` | show the default voices |

Main options for `build`:

| option | default | notes |
|---|---|---|
| `--lang es\|en` | `es` | build both into the same folder; the viewer has a language switch |
| `--tts edge\|piper` | `edge` | Piper voices are downloaded to `~/.cache/arena-narrator/piper` on first use |
| `--voice` | `es-MX-JorgeNeural` / `en-US-GuyNeural` (edge), `es_MX-ald-medium` / `en_US-lessac-medium` (piper) | any edge-tts voice name, any Piper voice name or a path to an `.onnx` file |
| `--rate` | — | e.g. `+10%` |
| `--provider` | `auto` | `anthropic`, `openrouter` (any model, default `anthropic/claude-opus-5.5`), `gemini`, `claude-cli` (local Claude Code, no key) or `none` (offline template, no LLM) |
| `--model` | provider default | e.g. `claude-opus-5-5`, `gemini-flash-latest`, `openai/gpt-6.1-sol` (OpenRouter) |
| `--engine` | — | path to a UCI engine such as Stockfish, which adds evaluations and blunder flags to the facts |
| `--chunk` | `30` | plies per LLM call; a running summary keeps long games coherent |
| `--regen` | — | ignore the cached script (scripts and audio clips are cached) |

`auto` picks Anthropic if `ANTHROPIC_API_KEY` is set, then OpenRouter (`OPENROUTER_API_KEY`), then Gemini (`GEMINI_API_KEY` / `GOOGLE_API_KEY`), then a local `claude` CLI.

## Output

```
out/109084577/
  episode.json              raw Kaggle data
  script.es.json            narration segments (intro, one per ply, outro)
  audio/es/edge/NNN-*.mp3   one clip per segment (re-used when text and voice are unchanged)
  narration.es.mp3          everything joined together (needs ffmpeg)
  manifest.es.json          what the viewers read
  index.html viewer.js viewer.css index.json
```

The output folder is a static site, so you can publish it as-is (GitHub Pages, any static host).

## How the narration stays honest

Models in Game Arena often hallucinate: they describe impossible lines, contradict themselves, or leave pieces hanging while describing an attack. The narrator LLM gets, for every move:

- the model's verbatim reasoning and how long it thought,
- the move in SAN and in **spoken form** ("caballo a efe seis, jaque"),
- facts from python-chess: capture, check, mate, material balance, and pieces left attacked and undefended (a heuristic),
- optionally engine evaluations,
- the full game score, so it can see what actually happened next.

It is instructed to criticise the reasoning only when those facts support it, and never to invent evaluations.

## Notes

- Only standard chess episodes are supported for now; other Game Arena games are rejected with a clear message.
- edge-tts uses Microsoft's online service, so the script text is sent to it. Piper runs fully offline.
- With `--provider claude-cli`, Claude Code's safeguards have occasionally flagged ordinary chess commentary. If that happens, use an API provider.
- Not affiliated with Kaggle, Google, OpenAI or Anthropic. Episode data is public at `kaggleusercontent.com/episodes/<id>.json`.

## Development

```bash
uv sync --all-extras
uv run pytest
uv run ruff check
```

---

## En español

**Convierte cualquier partida de ajedrez de [Kaggle Game Arena](https://www.kaggle.com/game-arena) en una narración centrada en lo que pensaba cada modelo.**

En Game Arena los modelos juegan sin motor y escriben su razonamiento antes de cada jugada. `arena-narrator` descarga la partida y un LLM escribe un guion de comentarista en **español o inglés** que sigue ese razonamiento jugada a jugada. Señala los errores de un modelo solo cuando hay hechos objetivos que lo respaldan. Después lo locuta con **edge-tts** (en línea, gratis) o **Piper** (sin conexión), y lo puedes ver sincronizado con un tablero ligero en el **navegador** o en la **terminal**.

```bash
uv sync --extra edge --extra anthropic
export OPENROUTER_API_KEY=...       # o ANTHROPIC_API_KEY / GEMINI_API_KEY
uv run arena-narrator build "https://www.kaggle.com/game-arena?episodeId=109084577" --lang es --tts piper
uv run arena-narrator view out/109084577
uv run arena-narrator play out/109084577 --from-ply 41
```

- `--provider none` genera una narración básica sin LLM, útil para probar sin API key.
- Con `--engine /usr/bin/stockfish` se añaden evaluaciones y se marcan los errores graves.
- Atajos del visor: espacio (reproducir/pausar), ← → (segmento anterior/siguiente), F (girar el tablero).

## License

MIT
