// Arena Narrator viewer: no dependencies. Reads manifest.<lang>.json produced by the CLI.
(() => {
  "use strict";

  const GLYPH = { k: "♚", q: "♛", r: "♜", b: "♝", n: "♞", p: "♟" };
  const UI = {
    en: { white: "White", black: "Black", reasoning: "Model reasoning", thought: "thought for",
          intro: "Introduction", outro: "Final words", none: "(no reasoning recorded)", start: "Start" },
    es: { white: "Blancas", black: "Negras", reasoning: "Razonamiento del modelo", thought: "pensó",
          intro: "Introducción", outro: "Cierre", none: "(sin razonamiento registrado)", start: "Inicio" },
  };
  const $ = (id) => document.getElementById(id);
  const audio = $("audio");

  let M = null;          // manifest
  let t = UI.en;
  let byPly = new Map(); // ply -> move
  let seg = 0;           // current segment index
  let playing = false;
  let flipped = false;
  let timer = null;

  // ---------- board ----------
  function parseFen(fen) {
    const rows = fen.split(" ")[0].split("/");
    return rows.map((r) => {
      const out = [];
      for (const ch of r) /\d/.test(ch) ? out.push(...Array(+ch).fill(null)) : out.push(ch);
      return out;
    });
  }

  function drawBoard(fen, from, to, checkColor) {
    const grid = parseFen(fen);
    const board = $("board");
    board.innerHTML = "";
    for (let i = 0; i < 64; i++) {
      const r = flipped ? 7 - Math.floor(i / 8) : Math.floor(i / 8);
      const f = flipped ? 7 - (i % 8) : i % 8;
      const name = "abcdefgh"[f] + (8 - r);
      const sq = document.createElement("div");
      sq.className = "sq " + ((r + f) % 2 === 0 ? "l" : "d");
      if (name === from || name === to) sq.classList.add("hl");
      const p = grid[r][f];
      if (p) {
        const isWhite = p === p.toUpperCase();
        if (p.toLowerCase() === "k" && checkColor && (checkColor === "white") === isWhite) {
          sq.classList.add("check");
        }
        const span = document.createElement("span");
        span.className = "pc " + (isWhite ? "w" : "b");
        span.textContent = GLYPH[p.toLowerCase()] + "︎";
        sq.appendChild(span);
      }
      const bottom = flipped ? 0 : 7, left = flipped ? 7 : 0;
      if (r === bottom) sq.insertAdjacentHTML("beforeend", `<span class="coord f">${"abcdefgh"[f]}</span>`);
      if (f === left) sq.insertAdjacentHTML("beforeend", `<span class="coord r">${8 - r}</span>`);
      board.appendChild(sq);
    }
  }

  // ---------- panel ----------
  function moveLabel(mv) {
    return `${mv.number}${mv.side === "white" ? "." : "..."} ${mv.san}`;
  }

  function show(i) {
    seg = Math.max(0, Math.min(i, M.segments.length - 1));
    const s = M.segments[seg];
    const mv = byPly.get(s.ply);
    if (mv) {
      const checkColor = mv.check ? (mv.side === "white" ? "black" : "white") : null;
      drawBoard(mv.fen, mv.from, mv.to, checkColor);
      $("move-title").textContent = moveLabel(mv);
      const time = mv.time != null ? ` · ${t.thought} ${Math.round(mv.time)} s` : "";
      $("move-meta").textContent = `${mv.player} (${t[mv.side]})${time}`;
      $("thoughts").textContent = mv.thoughts || t.none;
      $("thoughts-box").hidden = false;
    } else {
      drawBoard(M.start_fen);
      $("move-title").textContent = t.intro;
      $("move-meta").textContent = `${M.white} vs ${M.black}`;
      $("thoughts-box").hidden = true;
    }
    if (s.kind === "outro") {
      $("move-title").textContent = t.outro;
      $("thoughts-box").hidden = true;
      if (M.forfeit) {
        const f = M.forfeit;
        $("move-meta").textContent = `${f.player} (${t[f.side]}) · ${f.attempted}?? — ${f.reason}`;
        $("thoughts").textContent = f.thoughts || t.none;
        $("thoughts-box").hidden = false;
      }
    }
    $("caption").textContent = s.text;
    document.querySelectorAll(".moves .mv").forEach((el) => {
      el.classList.toggle("cur", +el.dataset.ply === s.ply && s.kind === "move");
    });
    const cur = document.querySelector(".moves .mv.cur");
    if (cur) cur.scrollIntoView({ block: "nearest" });
    $("progress-bar").style.width = `${(100 * (seg + 1)) / M.segments.length}%`;
  }

  // ---------- playback ----------
  function stopAudio() {
    clearTimeout(timer);
    audio.pause();
  }

  function playCurrent() {
    stopAudio();
    const s = M.segments[seg];
    if (s.audio) {
      audio.src = s.audio;
      audio.playbackRate = +$("speed").value;
      audio.play().catch(() => setPlaying(false));
    } else {
      const ms = ((s.duration || Math.max(2, s.text.length / 15)) * 1000) / +$("speed").value;
      timer = setTimeout(advance, ms);
    }
  }

  function advance() {
    if (!playing) return;
    if (seg >= M.segments.length - 1) return setPlaying(false);
    show(seg + 1);
    playCurrent();
  }

  function setPlaying(on) {
    playing = on;
    $("play").textContent = on ? "⏸" : "▶";
    if (on) playCurrent();
    else stopAudio();
  }

  function go(i) {
    show(i);
    if (playing) playCurrent();
  }

  audio.addEventListener("ended", advance);
  // If a clip cannot be loaded, keep going on a timer based on its measured duration.
  audio.addEventListener("error", () => {
    if (!playing) return;
    const s = M.segments[seg];
    const ms = ((s.duration || Math.max(2, s.text.length / 15)) * 1000) / +$("speed").value;
    clearTimeout(timer);
    timer = setTimeout(advance, ms);
  });

  // ---------- setup ----------
  function buildMoveList() {
    const ol = $("moves");
    ol.innerHTML = "";
    for (const mv of M.moves) {
      if (mv.side === "white" || mv.ply === 1) {
        ol.insertAdjacentHTML("beforeend", `<li class="num">${mv.number}.</li>`);
        if (mv.side === "black") ol.insertAdjacentHTML("beforeend", `<li></li>`);
      }
      const li = document.createElement("li");
      li.className = "mv";
      li.dataset.ply = mv.ply;
      li.textContent = mv.san;
      li.title = mv.player;
      li.addEventListener("click", () => {
        const idx = M.segments.findIndex((s) => s.kind === "move" && s.ply === mv.ply);
        if (idx >= 0) go(idx);
      });
      ol.appendChild(li);
    }
  }

  async function load(lang) {
    setPlaying(false);
    const res = await fetch(`manifest.${lang}.json`);
    M = await res.json();
    t = UI[M.lang] || UI.en;
    document.documentElement.lang = M.lang;
    byPly = new Map(M.moves.map((m) => [m.ply, m]));
    $("white-name").textContent = M.white;
    $("black-name").textContent = M.black;
    $("result").textContent = M.result;
    $("source").href = M.source;
    $("thoughts-label").textContent = t.reasoning;
    document.title = `${M.white} vs ${M.black} · Arena Narrator`;
    buildMoveList();
    show(0);
    const url = new URL(location);
    url.searchParams.set("lang", lang);
    history.replaceState(null, "", url);
  }

  async function init() {
    let langs = ["en"];
    try {
      langs = (await (await fetch("index.json")).json()).langs;
    } catch (_) { /* single manifest */ }
    const sel = $("lang");
    sel.innerHTML = langs.map((l) => `<option value="${l}">${l.toUpperCase()}</option>`).join("");
    const wanted = new URLSearchParams(location.search).get("lang");
    const lang = langs.includes(wanted) ? wanted : langs[0];
    sel.value = lang;
    sel.addEventListener("change", () => load(sel.value));
    await load(lang);
  }

  $("play").addEventListener("click", () => setPlaying(!playing));
  $("prev").addEventListener("click", () => go(seg - 1));
  $("next").addEventListener("click", () => go(seg + 1));
  $("first").addEventListener("click", () => go(0));
  $("last").addEventListener("click", () => go(M.segments.length - 1));
  $("flip").addEventListener("click", () => { flipped = !flipped; show(seg); });
  $("speed").addEventListener("change", () => { audio.playbackRate = +$("speed").value; });
  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "SELECT") return;
    if (e.key === " ") { e.preventDefault(); setPlaying(!playing); }
    else if (e.key === "ArrowRight") go(seg + 1);
    else if (e.key === "ArrowLeft") go(seg - 1);
    else if (e.key === "Home") go(0);
    else if (e.key === "End") go(M.segments.length - 1);
    else if (e.key === "f") { flipped = !flipped; show(seg); }
  });

  init().catch((err) => {
    $("caption").textContent = "Could not load manifest: " + err;
  });
})();
