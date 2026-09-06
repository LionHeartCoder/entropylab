/* Entropy Lab front end. Plain JS, no build step. */
(() => {
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const state = { meta: null, game: null, sources: new Set(), mouse: [], sound: true, busy: false, wheelTickets: null, settings: {} };

const STRATEGY_INFO = {
  pure: ["Pure entropy", "Every number equal. The slider does nothing here."],
  hot: ["Hot numbers", "Most-drawn numbers weigh more."],
  cold: ["Cold numbers", "Longest-overdue numbers weigh more."],
  pairs: ["Pairs", "Numbers from the most-drawn pairs get a boost."],
  lucky: ["Lucky numbers", "Your numbers weigh more; lock any to force them."],
  phrase: ["Phrase seed", "A word or date gives a repeatable base."],
};
const FILTER_INFO = {
  anti_split: ["Anti-split", "reject picks made only of birthday numbers (1-31)"],
  anti_pattern: ["Anti-pattern", "reject runs, sequences, same last digit"],
  balanced: ["Balanced", "mixed odd/even and high/low, sum in the usual range"],
  never_hit: ["Never hit", "reject combinations that already won"],
};

// ---------------------------------------------------------------- utils
const pad2 = n => String(n).padStart(2, "0");
const fmtNums = (game, main, bonus, hits = [], bonusHit = false) => {
  const g = gameByKey(game);
  const digit = g && !g.pools[0].distinct;
  const parts = main.map((n, i) => {
    const hit = digit ? hits.includes(i) : hits.includes(n);
    return `<span class="${hit ? "hitn" : ""}">${digit ? n : pad2(n)}</span>`;
  });
  let s = parts.join(digit ? "-" : " ");
  if (bonus != null && g && g.pools[1]) s += ` <span class="b ${bonusHit ? "hitn" : ""}">+${pad2(bonus)}</span>`;
  return s;
};
const gameByKey = k => state.meta && state.meta.games.find(g => g.key === k);
const ints = s => s.split(/[,\s]+/).map(x => x.trim()).filter(Boolean).map(Number).filter(n => !Number.isNaN(n));
const toast = (msg, err = false) => { const t = $("#toast"); t.textContent = msg; t.className = "toast" + (err ? " err" : ""); t.hidden = false; clearTimeout(t._h); t._h = setTimeout(() => t.hidden = true, 3500); };
// base path so the app also works when proxied under a sub-path such as /entropylab/
const BASE = location.pathname.endsWith("/") ? location.pathname : location.pathname.replace(/[^/]*$/, "");
const U = path => BASE + path.replace(/^\//, "");
const WS = path => `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${U(path)}`;
const api = async (path, opts) => { const r = await fetch(U(path), opts); if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail || m; } catch {} throw new Error(m); } return r.json(); };
const post = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const log = (msg, cls = "") => { const l = $("#log"); const t = new Date().toLocaleTimeString([], { hour12: false }); l.insertAdjacentHTML("beforeend", `<div class="${cls}"><span class="t">${t}</span>${msg}</div>`); l.scrollTop = l.scrollHeight; };

// ---------------------------------------------------------------- sound
let actx = null;
const beep = (freq = 660, dur = 0.06, type = "sine", gain = 0.05) => {
  if (!state.sound) return;
  try {
    actx = actx || new (window.AudioContext || window.webkitAudioContext)();
    const o = actx.createOscillator(), g = actx.createGain();
    o.type = type; o.frequency.value = freq; g.gain.value = gain;
    o.connect(g); g.connect(actx.destination);
    o.start(); g.gain.exponentialRampToValueAtTime(0.0001, actx.currentTime + dur); o.stop(actx.currentTime + dur);
  } catch {}
};
const fanfare = () => [523, 659, 784, 1046].forEach((f, i) => setTimeout(() => beep(f, 0.18, "triangle", 0.08), i * 110));
// synthesized foley: dice rattle + thud, coin whoosh + ping
let noiseBuf = null;
const noise = () => { if (!noiseBuf) { noiseBuf = actx.createBuffer(1, actx.sampleRate * 1.5, actx.sampleRate); const d = noiseBuf.getChannelData(0); for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1; } const s = actx.createBufferSource(); s.buffer = noiseBuf; return s; };
const sfx = {
  ctx() { if (!state.sound) return null; try { actx = actx || new (window.AudioContext || window.webkitAudioContext)(); return actx; } catch { return null; } },
  diceRoll(at = 0, dur = 1.2) {
    const c = this.ctx(); if (!c) return; const t0 = c.currentTime + at;
    const clicks = 6 + Math.floor(Math.random() * 5);
    for (let i = 0; i < clicks; i++) {
      const t = t0 + (i / clicks) * dur * 0.85 * (0.7 + 0.3 * Math.random());
      const s = noise(), f = c.createBiquadFilter(), g = c.createGain();
      f.type = "bandpass"; f.frequency.value = 1800 + Math.random() * 2200; f.Q.value = 2.5;
      g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.09 * (1 - i / clicks * 0.5), t + 0.004); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.045);
      s.connect(f); f.connect(g); g.connect(c.destination); s.start(t); s.stop(t + 0.06);
    }
    const thud = c.createOscillator(), tg = c.createGain(); thud.type = "sine";
    thud.frequency.setValueAtTime(170, t0 + dur); thud.frequency.exponentialRampToValueAtTime(60, t0 + dur + 0.12);
    tg.gain.setValueAtTime(0.0001, t0 + dur); tg.gain.exponentialRampToValueAtTime(0.18, t0 + dur + 0.006); tg.gain.exponentialRampToValueAtTime(0.0001, t0 + dur + 0.16);
    thud.connect(tg); tg.connect(c.destination); thud.start(t0 + dur); thud.stop(t0 + dur + 0.2);
  },
  coinFlip(at = 0, dur = 1.3, tails = false) {
    const c = this.ctx(); if (!c) return; const t0 = c.currentTime + at;
    const s = noise(), f = c.createBiquadFilter(), g = c.createGain();
    f.type = "bandpass"; f.Q.value = 1.2; f.frequency.setValueAtTime(600, t0); f.frequency.exponentialRampToValueAtTime(2400, t0 + dur * 0.5); f.frequency.exponentialRampToValueAtTime(500, t0 + dur);
    g.gain.setValueAtTime(0.0001, t0); g.gain.exponentialRampToValueAtTime(0.05, t0 + dur * 0.4); g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    s.connect(f); f.connect(g); g.connect(c.destination); s.start(t0); s.stop(t0 + dur);
    const base = tails ? 1900 : 2500;
    [1, 1.83, 2.71].forEach((h, i) => {
      const o = c.createOscillator(), og = c.createGain(); o.type = "sine"; o.frequency.value = base * h;
      const t = t0 + dur; og.gain.setValueAtTime(0.0001, t); og.gain.exponentialRampToValueAtTime(0.12 / (i + 1), t + 0.004); og.gain.exponentialRampToValueAtTime(0.0001, t + 0.7 - i * 0.15);
      o.connect(og); og.connect(c.destination); o.start(t); o.stop(t + 0.8);
    });
  },
};

// ---------------------------------------------------------------- confetti
const confetti = (n = 160) => {
  const c = $("#confetti"), ctx = c.getContext("2d");
  c.width = innerWidth; c.height = innerHeight;
  const cols = ["#22d3ee", "#a78bfa", "#f472b6", "#fbbf24", "#34d399"];
  const ps = Array.from({ length: n }, () => ({ x: Math.random() * c.width, y: -20 - Math.random() * 200, vx: (Math.random() - .5) * 3, vy: 2 + Math.random() * 4, r: 4 + Math.random() * 5, col: cols[Math.floor(Math.random() * cols.length)], a: Math.random() * 6 }));
  let t = 0;
  const step = () => {
    ctx.clearRect(0, 0, c.width, c.height);
    ps.forEach(p => { p.x += p.vx; p.y += p.vy; p.a += .1; ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.a); ctx.fillStyle = p.col; ctx.fillRect(-p.r / 2, -p.r / 2, p.r, p.r * .6); ctx.restore(); });
    if (++t < 220) requestAnimationFrame(step); else ctx.clearRect(0, 0, c.width, c.height);
  };
  step();
};

// ---------------------------------------------------------------- init
async function init() {
  state.meta = await api("/api/meta");
  state.settings = state.meta.settings || {};
  if (state.settings.theme) document.documentElement.dataset.theme = state.settings.theme;
  if (state.settings.sound === false) { state.sound = false; $("#sound").classList.remove("on"); } else $("#sound").classList.add("on");

  const gs = $("#game");
  gs.innerHTML = state.meta.games.map(g => `<option value="${g.key}">${g.name}</option>`).join("");
  $("#tickets-game").insertAdjacentHTML("beforeend", state.meta.games.map(g => `<option value="${g.key}">${g.name}</option>`).join(""));
  gs.value = state.settings.game || "powerball";
  state.game = gs.value;

  const rack = $("#sources");
  const on = new Set(state.settings.sources || state.meta.default_sources);
  rack.innerHTML = state.meta.sources.map(s => `
    <label class="src ${on.has(s.key) ? "on" : ""}" data-key="${s.key}" title="${s.description}">
      <input type="checkbox" ${on.has(s.key) ? "checked" : ""}>
      <i class="ti ${s.icon}"></i>
      <div><div class="name">${s.label}${s.online ? ' <span class="hint">online</span>' : ""}</div><div class="status">idle</div></div>
      <div class="meter"><span></span></div>
    </label>`).join("");
  state.sources = on;
  rack.addEventListener("change", e => {
    const l = e.target.closest(".src"); const k = l.dataset.key;
    if (e.target.checked) state.sources.add(k); else state.sources.delete(k);
    l.classList.toggle("on", e.target.checked);
    updateRack(); saveSettings();
  });

  $("#strategies").innerHTML = Object.entries(STRATEGY_INFO).map(([k, [name, d]], i) =>
    `<label class="chip" title="${d}"><input type="radio" name="strategy" value="${k}" ${i === 0 ? "checked" : ""}> ${name}</label>`).join("");
  $("#filters").innerHTML = Object.entries(FILTER_INFO).map(([k, [name, d]]) =>
    `<label class="chip" title="${d}"><input type="checkbox" name="filter" value="${k}"> ${name}</label>`).join("");

  $("#strategies").addEventListener("change", updateStrategy);
  $("#entropy").addEventListener("input", () => $("#entropy-out").textContent = $("#entropy").value + "%");
  $$("input[name=mode]").forEach(r => r.addEventListener("change", () => {
    $("#mode-hint").textContent = r.value === "drift" && r.checked ? "each base number rolls a random distance; slider sets how far" : "weights tilt toward your base, entropy flattens them";
  }));
  gs.addEventListener("change", () => { state.game = gs.value; onGameChange(); saveSettings(); });
  $("#generate").addEventListener("click", generate);
  $("#peek").addEventListener("click", peek);
  $("#sound").addEventListener("click", () => { state.sound = !state.sound; $("#sound").classList.toggle("on", state.sound); saveSettings(); beep(880); });
  $("#theme").addEventListener("click", () => { const d = document.documentElement; d.dataset.theme = d.dataset.theme === "light" ? "" : "light"; saveSettings(); });
  $$(".tabs button").forEach(b => b.addEventListener("click", () => showTab(b.dataset.tab)));
  $("#check").addEventListener("click", checkResults);
  $("#refresh-tickets").addEventListener("click", loadTickets);
  $("#tickets-game").addEventListener("change", loadTickets);
  $("#research-load").addEventListener("click", loadResearch);
  $("#arena-run").addEventListener("click", runArena);
  $("#wheel-run").addEventListener("click", buildWheel);
  $("#wheel-save").addEventListener("click", saveWheel);
  $("#wheel-kind").addEventListener("change", () => { const k = $("#wheel-kind").value; $("#wheel-guarantee-wrap").hidden = k !== "abbrev"; $("#wheel-key-wrap").hidden = k !== "key"; });
  $("#health-run").addEventListener("click", runHealth);
  $("#tool-kinds").addEventListener("change", updateToolOpts);
  $("#tool-run").addEventListener("click", runTool);
  $("#c-enc").addEventListener("click", () => cryptoRun("encrypt"));
  $("#c-dec").addEventListener("click", () => cryptoRun("decrypt"));
  $("#c-copy").addEventListener("click", () => navigator.clipboard.writeText($("#c-out").value).then(() => toast("copied")));
  $("#c-clear").addEventListener("click", () => { $("#c-text").value = ""; $("#c-out").value = ""; $("#c-pass").value = ""; });
  updateToolOpts();
  $("#trophies-load").addEventListener("click", loadTrophies);
  $("#tickets").addEventListener("change", () => $("#max-shared").disabled = Number($("#tickets").value) < 2);

  setupMousepad();
  // floating Generate button on phones: shows only when the real one is scrolled away on the Lab tab
  const fab = $("#fab");
  fab.addEventListener("click", () => { if ($("#tab-lab").classList.contains("active")) { $("#generate").click(); $("#generate").scrollIntoView({ behavior: "smooth", block: "center" }); } else if ($("#tab-tools").classList.contains("active")) { $("#tool-run").click(); $("#tool-out").scrollIntoView({ behavior: "smooth", block: "start" }); } });
  const updateFab = () => {
    const labOn = $("#tab-lab").classList.contains("active"), toolsOn = $("#tab-tools").classList.contains("active");
    const btn = labOn ? $("#generate") : toolsOn ? $("#tool-run") : null;
    if (!btn) { fab.classList.remove("show"); return; }
    const r = btn.getBoundingClientRect(); const visible = r.bottom > 0 && r.top < innerHeight;
    fab.classList.toggle("show", !visible && !state.busy);
  };
  addEventListener("scroll", updateFab, { passive: true }); addEventListener("resize", updateFab);
  $$(".tabs button").forEach(b => b.addEventListener("click", () => setTimeout(updateFab, 50)));
  setInterval(updateFab, 1500);
  $("#file-input").addEventListener("change", async e => {
    const f = e.target.files[0]; if (!f) { state.file = null; $("#file-info").textContent = "none"; return; }
    if (f.size > 40 * 1024 * 1024) { toast("file larger than 40 MB", true); e.target.value = ""; return; }
    const buf = await f.arrayBuffer();
    let bin = ""; const bytes = new Uint8Array(buf); for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    state.file = { name: f.name, b64: btoa(bin) };
    $("#file-info").textContent = `${f.name} · ${(f.size / 1024).toFixed(0)} KB`;
    if (f.type.startsWith("image/")) {
      if (peeking) peek();
      $("#cam").src = URL.createObjectURL(f); $("#vf-idle").hidden = true; $("#vf-info").textContent = "still image: " + f.name;
    }
    log(`file loaded: ${f.name} (${f.size.toLocaleString()} bytes)`);
  });
  updateStrategy();
  updateRack();
  onGameChange();
  setInterval(tickCountdown, 1000);
  log("Entropy Lab online. " + state.meta.sources.length + " sources in the rack." + (state.meta.hosted ? " Hosted mode: your camera and mic are captured in this browser and never stored." : ""));
  if (state.meta.hosted) { $("#peek").textContent = "Preview my camera"; $(".brand small").textContent = "Virginia Lottery edition · hosted"; }
}

function saveSettings() {
  const body = { game: state.game, sources: [...state.sources], sound: state.sound, theme: document.documentElement.dataset.theme || "" };
  post("/api/settings", body).catch(() => {});
}

function showTab(name) {
  $$(".tabs button").forEach(b => b.classList.toggle("active", b.dataset.tab === name));
  $$(".tab").forEach(t => t.classList.toggle("active", t.id === "tab-" + name));
  if (name === "tickets") loadTickets();
  if (name === "trophies") loadTrophies();
  if (name === "wheel") updateWheelOptions();
}

function updateRack() {
  const n = state.sources.size;
  $("#rack-hint").textContent = n === 0 ? "nothing selected" : n === state.meta.sources.length ? "all on" : n + " on";
  $("#mouse-wrap").hidden = !state.sources.has("mouse");
  $("#file-wrap").hidden = !state.sources.has("file");
  $("#phrase-wrap").hidden = !(state.sources.has("phrase") || $("input[name=strategy]:checked").value === "phrase");
}

function updateStrategy() {
  const s = $("input[name=strategy]:checked").value;
  $("#lucky-wrap").hidden = s !== "lucky";
  $("#entropy").disabled = s === "pure";
  updateRack();
}

function onGameChange() {
  const g = gameByKey(state.game);
  const p = g.pools[0];
  $("#count-wrap").hidden = !p.user_sets_count;
  if (p.user_sets_count) { $("#count").min = p.min_count; $("#count").max = p.max_count; $("#count").value = Math.min(p.count, p.max_count); }
  $("#lucky-bonus-wrap").hidden = !g.pools[1];
  $("#exclude").placeholder = `numbers you never want (${p.lo}-${p.hi})`;
  tickCountdown();
}

let nextCache = {};
async function refreshNext() { try { nextCache = await api("/api/next"); } catch {} }
function tickCountdown() {
  const g = gameByKey(state.game);
  const nd = nextCache[state.game] !== undefined ? nextCache[state.game] : g.next;
  const el = $("#countdown-text");
  if (!nd) { el.textContent = g.key === "keno" ? "draws every 4 minutes" : "no schedule"; return; }
  const secs = Math.max(0, Math.floor((new Date(nd.at) - Date.now()) / 1000));
  if (secs === 0) { refreshNext(); }
  const h = Math.floor(secs / 3600), m = Math.floor((secs % 3600) / 60), s = secs % 60;
  el.textContent = `${nd.session ? nd.session + " " : ""}draw in ${h > 0 ? h + "h " : ""}${pad2(m)}m ${pad2(s)}s`;
}
refreshNext();

// ---------------------------------------------------------------- mousepad
function setupMousepad() {
  const c = $("#mousepad"), ctx = c.getContext("2d");
  let last = null;
  const pos = e => { const r = c.getBoundingClientRect(); return [Math.round((e.clientX - r.left) * c.width / r.width), Math.round((e.clientY - r.top) * c.height / r.height)]; };
  const draw = e => {
    if (e.buttons !== 1 && e.pointerType === "mouse") return;
    const [x, y] = pos(e);
    state.mouse.push([x, y, Math.round(performance.now() * 1000)]);
    if (state.mouse.length > 4000) state.mouse.shift();
    ctx.strokeStyle = "#22d3ee"; ctx.lineWidth = 2; ctx.lineCap = "round";
    if (last) { ctx.beginPath(); ctx.moveTo(last[0], last[1]); ctx.lineTo(x, y); ctx.stroke(); }
    last = [x, y];
    $("#mouse-count").textContent = state.mouse.length + " samples";
  };
  c.addEventListener("pointermove", draw);
  c.addEventListener("pointerdown", e => { last = null; draw(e); });
  c.addEventListener("pointerup", () => last = null);
  c.addEventListener("pointerleave", () => last = null);
  c.addEventListener("dblclick", () => { state.mouse = []; ctx.clearRect(0, 0, c.width, c.height); $("#mouse-count").textContent = "0 samples"; });
}

// ---------------------------------------------------------------- browser capture (hosted mode)
// The server cannot see a visitor's camera, so frames and audio are captured here and sent up.
async function captureBrowser(wantCam, wantMic, frames = 24) {
  const out = { webcam_frames: [], audio_samples: [] };
  if (!wantCam && !wantMic) return out;
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { log("this browser cannot capture camera or microphone", "err"); return out; }
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({ video: wantCam ? { width: { ideal: 640 }, height: { ideal: 480 } } : false, audio: wantMic }); }
  catch (e) { log("camera/mic permission denied: " + e.message, "err"); return out; }
  const vid = $("#camvid"), img = $("#cam");
  try {
    const tasks = [];
    if (wantCam && stream.getVideoTracks().length) {
      tasks.push((async () => {
        vid.srcObject = stream; vid.hidden = false; img.removeAttribute("src"); $("#vf-idle").hidden = true; $("#viewfinder").classList.add("live"); $("#rec").hidden = false;
        await new Promise(r => { if (vid.readyState >= 2) r(); else vid.onloadeddata = r; });
        await new Promise(r => setTimeout(r, 350));
        const c = document.createElement("canvas"); c.width = vid.videoWidth || 640; c.height = vid.videoHeight || 480; const ctx = c.getContext("2d");
        for (let i = 0; i < frames; i++) {
          ctx.drawImage(vid, 0, 0, c.width, c.height);
          out.webcam_frames.push(c.toDataURL("image/jpeg", 0.7).split(",")[1]);
          $("#vf-info").textContent = `your camera frame ${i + 1}/${frames}`; setSourceStatus("webcam", `${i + 1}/${frames}`, "busy", 100 * (i + 1) / frames);
          if (i % 4 === 0) beep(440 + i * 10, 0.03, "square", 0.02);
          await new Promise(r => setTimeout(r, 65));
        }
      })());
    }
    if (wantMic && stream.getAudioTracks().length) {
      tasks.push((async () => {
        setSourceStatus("audio", "listening", "busy", 100);
        const ac = new (window.AudioContext || window.webkitAudioContext)();
        const src = ac.createMediaStreamSource(new MediaStream(stream.getAudioTracks()));
        const proc = ac.createScriptProcessor(4096, 1, 1); const chunks = [];
        proc.onaudioprocess = e => { const d = e.inputBuffer.getChannelData(0); for (let i = 0; i < d.length; i++) chunks.push(Math.max(-32768, Math.min(32767, Math.round(d[i] * 32767)))); };
        src.connect(proc); proc.connect(ac.destination);
        await new Promise(r => setTimeout(r, 1100));
        proc.disconnect(); src.disconnect(); await ac.close();
        out.audio_samples = chunks.slice(0, 48000);
        const step = Math.max(1, Math.floor(out.audio_samples.length / 240)); drawWave($("#wave"), out.audio_samples.filter((_, i) => i % step === 0));
      })());
    }
    await Promise.all(tasks);
  } finally {
    stream.getTracks().forEach(t => t.stop());
    vid.srcObject = null; vid.hidden = true; $("#rec").hidden = true; $("#viewfinder").classList.remove("live");
    if (out.webcam_frames.length) { img.src = "data:image/jpeg;base64," + out.webcam_frames[out.webcam_frames.length - 1]; $("#vf-info").textContent = "capture complete"; }
  }
  return out;
}
async function browserPayload(sources) {
  const wantCam = sources.includes("webcam"), wantMic = sources.includes("audio");
  return captureBrowser(wantCam, wantMic);
}

// ---------------------------------------------------------------- camera peek
let peeking = false;
let peekStream = null;
async function peekBrowser() {
  const vid = $("#camvid");
  if (peeking) { if (peekStream) peekStream.getTracks().forEach(t => t.stop()); peekStream = null; vid.srcObject = null; vid.hidden = true; peeking = false; $("#vf-idle").hidden = false; $("#viewfinder").classList.remove("live"); $("#vf-info").textContent = "camera idle"; $("#peek").textContent = "Peek camera"; return; }
  try { peekStream = await navigator.mediaDevices.getUserMedia({ video: true }); } catch (e) { toast("camera permission denied", true); return; }
  vid.srcObject = peekStream; vid.hidden = false; $("#cam").removeAttribute("src"); peeking = true; $("#vf-idle").hidden = true; $("#viewfinder").classList.add("live"); $("#vf-info").textContent = "your camera, preview only"; $("#peek").textContent = "Stop peek";
}
function peek() {
  if (state.meta && state.meta.hosted) return peekBrowser();
  const img = $("#cam");
  if (peeking) { img.removeAttribute("src"); fetch(U("/api/peek/stop"), { method: "POST" }).catch(() => {}); peeking = false; $("#vf-idle").hidden = false; $("#viewfinder").classList.remove("live"); $("#vf-info").textContent = "camera idle"; $("#peek").textContent = "Peek camera"; return; }
  const camIdx = state.sources.has("camera1") && !state.sources.has("camera") ? 1 : 0;
  img.src = U(`/stream/camera/${camIdx}?t=${Date.now()}`);
  peeking = true; $("#vf-idle").hidden = true; $("#viewfinder").classList.add("live"); $("#vf-info").textContent = "peeking, stops after 20 s"; $("#peek").textContent = "Stop peek";
  setTimeout(() => { if (peeking) peek(); }, 20500);
}

// ---------------------------------------------------------------- generate
function readRequest() {
  const g = gameByKey(state.game);
  const body = {
    game: state.game,
    sources: [...state.sources],
    strategy: $("input[name=strategy]:checked").value,
    entropy: Number($("#entropy").value) / 100,
    mode: $("input[name=mode]:checked").value,
    lucky: ints($("#lucky").value), locked: ints($("#locked").value),
    lucky_bonus: $("#lucky-bonus").value ? Number($("#lucky-bonus").value) : null,
    exclude: ints($("#exclude").value),
    filters: $$("input[name=filter]:checked").map(i => i.value),
    phrase: $("#phrase").value,
    tickets: Number($("#tickets").value), max_shared: Number($("#max-shared").value),
    shadow: $("#shadow").checked, label: $("#label").value, current_era: $("#era").checked,
    mouse_events: state.mouse, frames: 24, mic_seconds: 1.0, save: true,
    file_b64: state.file ? state.file.b64 : null, file_name: state.file ? state.file.name : "",
  };
  if (g.pools[0].user_sets_count) body.count = Number($("#count").value);
  return body;
}

function setSourceStatus(key, text, cls, pct) {
  const el = $(`.src[data-key="${key}"]`); if (!el) return;
  $(".status", el).textContent = text;
  const m = $(".meter", el); m.className = "meter " + (cls || "");
  if (pct != null) $("span", m).style.width = pct + "%";
}

async function generate() {
  if (state.busy) return;
  if (state.sources.size === 0) { toast("Turn on at least one entropy source", true); return; }
  if (peeking) peek();
  state.busy = true;
  const btn = $("#generate"); btn.disabled = true; btn.classList.add("working"); $("span", btn).textContent = "Gathering";
  $("#tray").innerHTML = `<div class="hopper">${Array.from({ length: 7 }, (_, i) => `<div class="ball" style="animation-delay:${(i * 0.11).toFixed(2)}s">·</div>`).join("")}</div>`;
  $("#receipt").textContent = ""; $("#poolinfo").textContent = "";
  $$(".src").forEach(el => setSourceStatus(el.dataset.key, state.sources.has(el.dataset.key) ? "queued" : "off", "", 0));
  const body = readRequest();
  log(`Generating ${body.tickets > 1 ? body.tickets + " tickets" : "a pick"} for ${gameByKey(body.game).name} using ${body.sources.join(", ")}`);
  Object.assign(body, await browserPayload(body.sources));
  const ws = new WebSocket(WS("/ws/generate"));
  const img = $("#cam"), wave = $("#wave");
  let picks = 0;
  ws.onopen = () => ws.send(JSON.stringify(body));
  ws.onerror = () => { toast("connection failed", true); finish(); };
  ws.onclose = () => finish();
  ws.onmessage = ev => {
    const m = JSON.parse(ev.data);
    switch (m.type) {
      case "source_start": setSourceStatus(m.source, "working", "busy", 100); break;
      case "progress": setSourceStatus(m.source, `${m.i}/${m.n}`, "busy", 100 * m.i / m.n); if (m.i % 4 === 0) beep(440 + m.i * 10, 0.03, "square", 0.02); break;
      case "frame":
        img.src = "data:image/jpeg;base64," + m.jpeg; $("#vf-idle").hidden = true; $("#viewfinder").classList.add("live"); $("#rec").hidden = false;
        $("#vf-info").textContent = `${m.source} frame ${m.i}/${m.n}`; break;
      case "waveform": drawWave(wave, m.samples); break;
      case "source_done": {
        const r = m.result;
        if (r.ok) { setSourceStatus(r.key, `${r.entropy_bits_per_byte.toFixed(2)} b/B · ${r.elapsed_ms} ms`, "ok", 100); log(`<span class="ok">✓</span> ${r.key}: ${r.detail}`); beep(880, 0.05); }
        else { setSourceStatus(r.key, "failed", "err", 100); log(`<span class="err">✗</span> ${r.key}: ${r.error}`, "err"); beep(220, 0.15, "sawtooth", 0.04); }
        break;
      }
      case "pool":
        $("#rec").hidden = true; $("#viewfinder").classList.remove("live"); $("#vf-info").textContent = "capture complete";
        $("#receipt").innerHTML = `receipt <b>${m.receipt}</b>`;
        $("#poolinfo").innerHTML = `<span>${m.pool.ok_sources.length} sources mixed</span><span>${m.pool.bits_in.toLocaleString()} bits in</span>${m.pool.failed_sources.length ? `<span style="color:var(--bad)">${m.pool.failed_sources.join(", ")} failed</span>` : ""}`;
        log(`Pool sealed: ${m.pool.bits_in.toLocaleString()} bits from ${m.pool.ok_sources.join(", ")} → receipt ${m.receipt}`);
        $("span", btn).textContent = "Drawing";
        break;
      case "pick": { const h = $("#tray .hopper"); if (h) h.remove(); renderPick(m, picks++); break; }
      case "error": toast(m.message, true); log(m.message, "err"); break;
      case "done": ws.close(); break;
    }
  };
  function finish() {
    const h = $("#tray .hopper"); if (h) h.remove();
    state.busy = false; btn.disabled = false; btn.classList.remove("working"); $("span", btn).textContent = "Generate";
    $("#rec").hidden = true; $("#viewfinder").classList.remove("live");
    if (picks > 0) { log(`${picks} ticket${picks > 1 ? "s" : ""} saved. Next draw: ${nextCache[state.game]?.date || ""}`); refreshNext(); }
  }
}

function renderPick(m, idx) {
  const g = gameByKey(m.pick.game);
  const digit = !g.pools[0].distinct;
  const row = document.createElement("div"); row.className = "ticket-row";
  row.innerHTML = `<span class="tid">${m.ticket_id ? "#" + m.ticket_id : "—"}</span>`;
  m.pick.main.forEach((n, i) => {
    const b = document.createElement("div"); b.className = "ball" + (digit ? " digit" : ""); b.textContent = digit ? n : pad2(n);
    b.style.animationDelay = (idx * 0.1 + i * 0.12) + "s"; row.appendChild(b);
    setTimeout(() => beep(520 + i * 60, 0.08, "triangle", 0.05), (idx * 0.1 + i * 0.12) * 1000 + 250);
  });
  if (m.pick.bonus != null && g.pools[1]) {
    const plus = document.createElement("span"); plus.className = "plus"; plus.textContent = "+"; row.appendChild(plus);
    const b = document.createElement("div"); b.className = "ball bonus"; b.textContent = pad2(m.pick.bonus);
    b.style.animationDelay = (idx * 0.1 + m.pick.main.length * 0.12) + "s"; row.appendChild(b);
    b.title = g.pools[1].name;
  }
  if (m.pick.strategy !== "pure" && m.pick.base_main) {
    const base = document.createElement("div"); base.className = "base-row";
    base.innerHTML = `<span>base</span>` + m.pick.base_main.map(n => `<span class="ball base">${digit ? n : pad2(n)}</span>`).join("") +
      (m.pick.base_bonus != null ? `<span class="ball base bonus">${pad2(m.pick.base_bonus)}</span>` : "") +
      `<span style="margin-left:8px">${Math.round(m.pick.entropy * 100)}% entropy · ${m.pick.mode}${m.pick.attempts > 1 ? " · " + m.pick.attempts + " tries" : ""}</span>`;
    row.appendChild(base);
  }
  $("#tray").appendChild(row);
  if (m.pick.notes && m.pick.notes.length) log(m.pick.notes.join("; "));
}

function drawWave(c, samples) {
  const ctx = c.getContext("2d"); c.width = c.clientWidth; const h = c.height;
  ctx.clearRect(0, 0, c.width, h);
  ctx.strokeStyle = "#22d3ee"; ctx.lineWidth = 1.5; ctx.beginPath();
  const max = Math.max(1, ...samples.map(Math.abs));
  samples.forEach((s, i) => { const x = i / samples.length * c.width, y = h / 2 - (s / max) * (h / 2 - 4); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
  ctx.stroke();
}

// ---------------------------------------------------------------- tickets
async function loadTickets() {
  const game = $("#tickets-game").value;
  const rows = await api("/api/tickets" + (game ? "?game=" + game : ""));
  const tb = $("#tickets-table tbody");
  if (!rows.length) { tb.innerHTML = `<tr><td colspan="8" class="hint">No tickets yet. Generate one in the Lab.</td></tr>`; return; }
  tb.innerHTML = rows.map(t => {
    const g = gameByKey(t.game); const digit = g && !g.pools[0].distinct;
    let hits = [], bhit = false, res = `<span class="badge pending">waiting for ${t.target_date || "draw"}${t.session ? " " + t.session : ""}</span>`;
    if (t.checked_date) {
      if (digit) hits = t.main.map((n, i) => n === t.result_main[i] ? i : -1).filter(i => i >= 0); else hits = t.main.filter(n => t.result_main.includes(n));
      bhit = !!t.match_bonus;
      const win = t.match_main > 0 || bhit;
      const cls = /jackpot|exact|life|100,000/i.test(t.prize) ? "jackpot" : win ? "win" : "";
      res = `<span class="badge ${cls}">${t.prize}</span><div class="hint mono">drew ${fmtNums(t.game, t.result_main, t.result_bonus)}</div>`;
    }
    return `<tr>
      <td class="mono">${t.id}${t.shadow ? ' <span class="badge shadow">shadow</span>' : ""}</td>
      <td>${g ? g.name : t.game}${t.label ? `<div class="hint">${t.label}</div>` : ""}</td>
      <td class="nums">${fmtNums(t.game, t.main, t.bonus, hits, bhit)}</td>
      <td class="hint">${t.target_date || ""} ${t.session || ""}</td>
      <td class="hint">${t.strategy}${t.strategy !== "pure" && t.strategy !== "wheel" ? " " + Math.round(t.entropy * 100) + "%" : ""}${t.filters.length ? "<br>" + t.filters.join(", ") : ""}</td>
      <td class="hint">${t.sources.join(", ")}<br><span class="mono">${t.seed_hash}</span></td>
      <td>${res}</td>
      <td><button class="mini" data-del="${t.id}" title="Delete"><i class="ti ti-trash"></i></button></td>
    </tr>`;
  }).join("");
  $$("[data-del]", tb).forEach(b => b.addEventListener("click", async () => { if (confirm("Delete ticket #" + b.dataset.del + "?")) { await fetch(U("/api/tickets/" + b.dataset.del), { method: "DELETE" }); loadTickets(); } }));
}

async function checkResults() {
  $("#check-summary").textContent = "Fetching official results…";
  try {
    const r = await post("/api/check", {});
    const wins = r.checked.filter(c => c.match_main > 0 || c.match_bonus);
    $("#check-summary").textContent = `${r.checked.length} ticket${r.checked.length === 1 ? "" : "s"} checked, ${wins.length} with a match, ${r.pending.length} still waiting for a draw.`;
    if (wins.length) { fanfare(); if (wins.some(w => w.match_main >= 3 || /jackpot|exact/i.test(w.prize))) confetti(); toast(`${wins.length} ticket${wins.length > 1 ? "s" : ""} matched!`); }
    loadTickets();
  } catch (e) { $("#check-summary").textContent = ""; toast(e.message, true); }
}

// ---------------------------------------------------------------- research
function barChart(freq, hot = [], cold = [], step = 1) {
  const keys = Object.keys(freq).map(Number).sort((a, b) => a - b);
  const max = Math.max(1, ...keys.map(k => freq[k]));
  return `<div class="bars-wrap"><div class="bars">${keys.map(k => `<div class="${hot.includes(k) ? "hot" : cold.includes(k) ? "cold" : ""}" style="height:${100 * freq[k] / max}%" title="${k}: ${freq[k]}">${(k % step === 0 || keys.length <= 20) ? `<span>${k}</span>` : ""}</div>`).join("")}</div></div>`;
}
async function loadResearch() {
  const el = $("#research"); el.innerHTML = `<p class="hint">Loading history…</p>`;
  try {
    const s = await api(`/api/stats/${state.game}?era=${$("#research-era").checked}`);
    const g = gameByKey(state.game);
    if (!s.available) { el.innerHTML = `<p class="hint">${s.reason}</p>`; return; }
    let h = `<div class="cards">
      <div class="card"><div class="label">Draws analysed</div><div class="value">${s.draws_used.toLocaleString()}</div><div class="sub">of ${s.draws_total.toLocaleString()} on file · ${s.first_date} to ${s.last_date}</div></div>
      <div class="card"><div class="label">Latest draw</div><div class="value" style="font-size:18px">${s.latest ? fmtNums(state.game, s.latest.main, s.latest.bonus) : "—"}</div><div class="sub">${s.latest ? s.latest.date + " " + s.latest.session : ""}</div></div>
      ${s.sums ? `<div class="card"><div class="label">Typical sum</div><div class="value">${s.sums.p10}–${s.sums.p90}</div><div class="sub">median ${s.sums.median}, extremes ${s.sums.min}–${s.sums.max}</div></div>` : ""}
    </div>`;
    if (s.digits) {
      h += `<div class="section-title">Digit frequency by position</div><div class="cards">` + s.digits.map((d, i) => `<div class="card"><div class="label">Position ${i + 1}</div>${barChart(d)}</div>`).join("") + `</div>`;
    } else {
      h += `<div class="section-title">Main numbers: how often each was drawn</div>${barChart(s.main.frequency, s.main.hot, s.main.cold, 5)}
        <div class="legend"><span><i style="background:var(--warn)"></i>hot (top 10)</span><span><i style="background:var(--accent2)"></i>cold (most overdue)</span></div>
        <div class="two"><div><div class="section-title">Hot</div><div class="numgrid">${s.main.hot.map(n => `<span class="n hot">${pad2(n)} <small>×${s.main.frequency[n]}</small></span>`).join("")}</div></div>
        <div><div class="section-title">Cold (draws since seen)</div><div class="numgrid">${s.main.cold.map(n => `<span class="n cold">${pad2(n)} <small>${s.main.gaps[n]}</small></span>`).join("")}</div></div></div>`;
      if (s.bonus) h += `<div class="section-title">${g.pools[1].name}</div>${barChart(s.bonus.frequency, s.bonus.hot, s.bonus.cold, 1)}`;
      if (s.pairs) h += `<div class="two"><div><div class="section-title">Most-drawn pairs</div><div class="numgrid">${s.pairs.slice(0, 15).map(p => `<span class="n">${p.pair.map(pad2).join(" & ")} <small>×${p.count}</small></span>`).join("")}</div></div>
        <div><div class="section-title">Most-drawn triplets</div><div class="numgrid">${s.triplets.slice(0, 10).map(p => `<span class="n">${p.triplet.map(pad2).join(" ")} <small>×${p.count}</small></span>`).join("")}</div></div></div>`;
      if (s.odd_even) h += `<div class="section-title">Odd / even splits</div>` + Object.entries(s.odd_even).map(([k, v]) => `<div class="hbar"><span>${k}</span><div class="bar"><span style="width:${100 * v / s.draws_used}%"></span></div><span class="mono">${(100 * v / s.draws_used).toFixed(1)}%</span></div>`).join("");
    }
    const recent = await api(`/api/results/${state.game}?limit=15`);
    h += `<div class="section-title">Recent results</div><div class="table-wrap"><table><thead><tr><th>Date</th><th>Draw</th><th>Numbers</th></tr></thead><tbody>` +
      recent.map(d => `<tr><td>${d.date}</td><td class="hint">${d.session}</td><td class="nums">${fmtNums(state.game, d.main, d.bonus)}${d.fireball != null ? ` <span class="hint">fireball ${d.fireball}</span>` : ""}</td></tr>`).join("") + `</tbody></table></div>`;
    el.innerHTML = h;
  } catch (e) { el.innerHTML = `<p class="hint">${e.message}</p>`; }
}

// ---------------------------------------------------------------- arena
async function runArena() {
  const el = $("#arena"); el.innerHTML = `<p class="hint">Running the last ${$("#arena-n").value} draws through every strategy…</p>`;
  try {
    const a = await api(`/api/arena/${state.game}?n=${$("#arena-n").value}&window=${$("#arena-window").value}&entropy=${$("#arena-entropy").value}`);
    if (!a.available) { el.innerHTML = `<p class="hint">${a.reason}</p>`; return; }
    const max = Math.max(a.expected_avg_match, ...Object.values(a.results).map(r => r.avg_match)) * 1.15;
    el.innerHTML = `<p class="hint">${a.draws_tested} real draws · rolling window ${a.window} · entropy ${Math.round(a.entropy * 100)}%</p>` +
      a.leaderboard.map((s, i) => { const r = a.results[s]; return `<div class="hbar"><span>${i === 0 ? "🏆 " : ""}${STRATEGY_INFO[s] ? STRATEGY_INFO[s][0] : s}</span><div class="bar"><span style="width:${100 * r.avg_match / max}%"></span></div><span class="mono">${r.avg_match.toFixed(3)}</span></div><div class="hint" style="margin:-2px 0 6px 100px">3+ matches: ${r.three_plus} · spread ${Object.entries(r.distribution).map(([k, v]) => k + ":" + v).join("  ")}</div>`; }).join("") +
      `<div class="hbar expected"><span>Expected</span><div class="bar"><span style="width:${100 * a.expected_avg_match / max}%"></span></div><span class="mono">${a.expected_avg_match.toFixed(3)}</span></div>
      <p class="note"><i class="ti ti-info-circle"></i> Run it again and the leaderboard reshuffles. That is the point: over time every method converges on the expected average.</p>`;
    beep(660, 0.1);
  } catch (e) { el.innerHTML = `<p class="hint">${e.message}</p>`; }
}

// ---------------------------------------------------------------- wheel
function updateWheelOptions() {
  const g = gameByKey(state.game); const k = g.pools[0].count;
  $("#wheel-guarantee").innerHTML = Array.from({ length: k - 1 }, (_, i) => i + 2).map(n => `<option value="${n}" ${n === Math.min(3, k) ? "selected" : ""}>${n} if ${n}</option>`).join("");
  $("#wheel-note").innerHTML = `<i class="ti ti-info-circle"></i> ${g.name} plays ${k} numbers per ticket. ` + (g.pools[0].distinct ? "An abbreviated wheel with guarantee 3 means: if 3 of your numbers are drawn, at least one ticket holds all 3." : "Wheeling only makes sense for games with distinct numbers.");
}
async function buildWheel() {
  const el = $("#wheel"); el.innerHTML = `<p class="hint">Building…</p>`; $("#wheel-save").hidden = true;
  try {
    const r = await post("/api/wheel", { game: state.game, numbers: ints($("#wheel-numbers").value), kind: $("#wheel-kind").value, guarantee: Number($("#wheel-guarantee").value), key: Number($("#wheel-key").value) });
    state.wheelTickets = r.tickets;
    el.innerHTML = `<p class="hint">${r.count} tickets (a full wheel of these numbers would be ${r.info.full_tickets}).</p><div class="table-wrap"><table><tbody>` +
      r.tickets.map((t, i) => `<tr><td class="mono hint">${i + 1}</td><td class="nums">${fmtNums(state.game, t, null)}</td></tr>`).join("") + `</tbody></table></div>`;
    $("#wheel-save").hidden = false; beep(660, 0.1);
  } catch (e) { el.innerHTML = `<p class="hint">${e.message}</p>`; }
}
async function saveWheel() {
  const g = gameByKey(state.game);
  const tickets = state.wheelTickets.map(t => ({ main: t, bonus: g.pools[1] ? 1 + Math.floor(crypto.getRandomValues(new Uint32Array(1))[0] / 4294967296 * (g.pools[1].hi - g.pools[1].lo + 1)) : null }));
  const r = await post("/api/tickets/bulk", { game: state.game, tickets, strategy: "wheel", label: "wheel " + $("#wheel-kind").value });
  toast(`${r.ids.length} wheel tickets saved`); $("#wheel-save").hidden = true;
}

// ---------------------------------------------------------------- tools
function toolKind() { return $("input[name=tool]:checked").value; }
function updateToolOpts() {
  const k = toolKind();
  $$(".tool-opts").forEach(el => el.hidden = el.dataset.for !== k);
}
function toolOpts() {
  const k = toolKind();
  switch (k) {
    case "numbers": return { lo: Number($("#t-lo").value), hi: Number($("#t-hi").value), count: Number($("#t-count").value), distinct: $("#t-distinct").checked, sort: $("#t-sort").checked };
    case "floats": return { count: Number($("#t-fcount").value), decimals: Number($("#t-decimals").value) };
    case "dice": return { sides: Number($("#t-sides").value), count: Number($("#t-dcount").value) };
    case "coins": return { count: Number($("#t-ccount").value) };
    case "shuffle": return { items: $("#t-items").value };
    case "pick": return { items: $("#t-pitems").value, count: Number($("#t-pcount").value) };
    case "password": return { length: Number($("#t-plen").value), classes: $$(".pclass:checked").map(i => i.value), exclude_ambiguous: $("#t-ambig").checked, require_each: $("#t-each").checked, custom: $("#t-custom").value };
    case "passphrase": return { count: Number($("#t-words").value), separator: $("#t-sep").value, capitalize: $("#t-cap").checked, add_number: $("#t-num").checked };
    case "pin": return { length: Number($("#t-pinlen").value) };
    case "key": return { bits: Number($("#t-bits").value), format: $("#t-fmt").value };
    case "uuid": return { count: Number($("#t-ucount").value) };
  }
  return {};
}
function strengthBadge(bits) {
  if (bits == null) return "";
  const [label, col] = bits >= 128 ? ["excellent", "var(--ok)"] : bits >= 80 ? ["strong", "var(--accent)"] : bits >= 50 ? ["okay", "var(--warn)"] : ["weak", "var(--bad)"];
  return `<span class="strength" style="border:1px solid ${col};color:${col}">${bits} bits · ${label}</span>`;
}
function copyBtn(text) {
  const b = document.createElement("button"); b.className = "mini"; b.innerHTML = '<i class="ti ti-copy"></i>';
  b.title = "Copy"; b.addEventListener("click", () => navigator.clipboard.writeText(text).then(() => toast("copied"), () => toast("copy failed", true)));
  return b;
}
// six-sided die: which of the 9 pip cells light up per face
const PIPS = { 1: [4], 2: [0, 8], 3: [0, 4, 8], 4: [0, 2, 6, 8], 5: [0, 2, 4, 6, 8], 6: [0, 2, 3, 5, 6, 8] };
// rotation that brings each face to the front
const FACE_ROT = { 1: [0, 0], 6: [0, 180], 3: [0, -90], 4: [0, 90], 5: [-90, 0], 2: [90, 0] };
function dieD6(n, delay) {
  const d = document.createElement("div"); d.className = "d6";
  const [rx, ry] = FACE_ROT[n];
  const spinsX = 360 * (2 + Math.floor(Math.random() * 2)), spinsY = 360 * (2 + Math.floor(Math.random() * 2));
  d.style.setProperty("--end", `rotateX(${spinsX + rx}deg) rotateY(${spinsY + ry}deg)`);
  d.style.animationDelay = delay + "s";
  for (let f = 1; f <= 6; f++) {
    const face = document.createElement("div"); face.className = "face f" + f;
    for (let c = 0; c < 9; c++) { const p = document.createElement("i"); if (PIPS[f].includes(c)) p.className = "on"; face.appendChild(p); }
    d.appendChild(face);
  }
  return d;
}
function polyDie(n, sides, delay) {
  const d = document.createElement("div"); d.className = "poly"; d.style.animationDelay = delay + "s";
  const pts = sides === 4 ? 3 : sides === 8 ? 4 : sides === 10 ? 5 : sides === 12 ? 5 : sides === 20 ? 6 : 8;
  const col = { 4: "#f472b6", 8: "#a78bfa", 10: "#34d399", 12: "#fbbf24", 20: "#22d3ee" }[sides] || "#60a5fa";
  const path = Array.from({ length: pts }, (_, i) => { const a = -Math.PI / 2 + i * 2 * Math.PI / pts; return `${31 + 29 * Math.cos(a)},${31 + 29 * Math.sin(a)}`; }).join(" ");
  d.innerHTML = `<svg viewBox="0 0 62 62"><polygon points="${path}" fill="${col}" stroke="rgba(255,255,255,.5)" stroke-width="2" stroke-linejoin="round"/></svg><span>${n}</span>`;
  return d;
}
function coinEl(v, delay) {
  const c = document.createElement("div"); c.className = "coin";
  const turns = 360 * (2 + Math.floor(Math.random() * 2)) + (v === "T" ? 180 : 0);
  c.style.setProperty("--turns", turns + "deg"); c.style.animationDelay = delay + "s";
  c.innerHTML = `<div class="side heads">H</div><div class="side tails">T</div>`;
  return c;
}
function renderToolResult(kind, r) {
  const box = document.createElement("div"); box.className = "tool-result";
  const val = document.createElement("div"); val.className = "val";
  let text = "";
  if (kind === "coins") {
    text = r.values.join(" ");
    const row = document.createElement("div"); row.className = "coin-row";
    const shown = r.values.slice(0, 60);
    shown.forEach((v, i) => { row.appendChild(coinEl(v, i * 0.08)); if (i < 12) sfx.coinFlip(i * 0.08, 1.3, v === "T"); });
    val.appendChild(row);
    val.insertAdjacentHTML("beforeend", `<div class="coin-tally"><b class="h">${r.heads}</b> heads · <b class="t">${r.tails}</b> tails${r.values.length > 60 ? ` · showing 60 of ${r.values.length}: ${r.values.join("")}` : ""}</div>`);
  } else if (kind === "dice") {
    text = r.values.join(" ");
    const row = document.createElement("div"); row.className = "dice-row";
    const shown = r.values.slice(0, 40);
    shown.forEach((v, i) => { row.appendChild(r.sides === 6 ? dieD6(v, i * 0.12) : polyDie(v, r.sides, i * 0.1)); if (i < 10) sfx.diceRoll(i * (r.sides === 6 ? 0.12 : 0.1), r.sides === 6 ? 1.25 : 0.95); });
    val.appendChild(row);
    val.insertAdjacentHTML("beforeend", `<div class="dice-total">d${r.sides} × ${r.values.length} · total <b>${r.total}</b>${r.values.length > 40 ? ` · showing 40: ${r.values.join(" ")}` : ""}</div>`);
  } else if (kind === "numbers") {
    text = r.values.join(", ");
    if (r.values.length <= 20) {
      const row = document.createElement("div"); row.className = "ticket-row";
      r.values.forEach((n, i) => { const b = document.createElement("div"); b.className = "ball"; b.textContent = n; b.style.animationDelay = (i * 0.1) + "s"; if (String(n).length > 3) b.style.fontSize = "13px"; row.appendChild(b); setTimeout(() => beep(520 + i * 40, 0.07, "triangle", 0.04), i * 100 + 250); });
      val.appendChild(row);
      val.insertAdjacentHTML("beforeend", `<div class="meta">${r.bits} bits drawn</div>`);
    } else {
      val.innerHTML = `${r.values.join(", ")}<div class="meta">${r.bits} bits drawn</div>`;
    }
  }
  else if (r.values) { text = r.values.join("\n"); val.innerHTML = r.values.length > 1 ? `<ol style="margin:0;padding-left:20px">${r.values.map(v => `<li>${v}</li>`).join("")}</ol>` : String(r.values[0]); }
  else { text = r.value; val.innerHTML = `${r.value}<div class="meta">${kind === "key" ? r.format + " " : ""}${strengthBadge(r.bits)}${r.alphabet_size ? " · alphabet " + r.alphabet_size : ""}${r.words ? " · " + r.words.toLocaleString() + " words" : ""}</div>`; }
  box.appendChild(val); box.appendChild(copyBtn(text));
  $("#tool-out").appendChild(box);
}
async function runTool() {
  if (state.busy) return;
  if (state.sources.size === 0) { toast("Turn on at least one entropy source in the Lab", true); return; }
  if (peeking) peek();
  state.busy = true;
  const btn = $("#tool-run"); btn.disabled = true; btn.classList.add("working");
  $("#tool-out").innerHTML = ""; const st = $("#tool-status"); st.textContent = "gathering entropy from " + [...state.sources].join(", ");
  const body = { sources: [...state.sources], kind: toolKind(), opts: toolOpts(), runs: Number($("#t-runs").value), mouse_events: state.mouse, phrase: $("#phrase").value, frames: 24, mic_seconds: 1.0, file_b64: state.file ? state.file.b64 : null, file_name: state.file ? state.file.name : "" };
  Object.assign(body, await browserPayload(body.sources));
  const ws = new WebSocket(WS("/ws/tools"));
  const done = [];
  ws.onopen = () => ws.send(JSON.stringify(body));
  ws.onerror = () => { toast("connection failed", true); finish(); };
  ws.onclose = () => finish();
  ws.onmessage = ev => {
    const m = JSON.parse(ev.data);
    switch (m.type) {
      case "source_start": setSourceStatus(m.source, "working", "busy", 100); break;
      case "progress": setSourceStatus(m.source, `${m.i}/${m.n}`, "busy", 100 * m.i / m.n); st.textContent = `${m.source} ${m.i}/${m.n}`; break;
      case "frame": $("#cam").src = "data:image/jpeg;base64," + m.jpeg; $("#vf-idle").hidden = true; break;
      case "waveform": drawWave($("#wave"), m.samples); break;
      case "source_done": { const r = m.result; done.push(r.key + (r.ok ? "" : " ✗")); setSourceStatus(r.key, r.ok ? `${r.entropy_bits_per_byte.toFixed(2)} b/B · ${r.elapsed_ms} ms` : "failed", r.ok ? "ok" : "err", 100); st.textContent = done.join(", "); beep(r.ok ? 880 : 220, 0.05); break; }
      case "pool": st.textContent = `pool sealed: ${m.pool.bits_in.toLocaleString()} bits from ${m.pool.ok_sources.join(", ")} · receipt ${m.receipt}`; break;
      case "result": renderToolResult(m.kind, m.result); beep(660, 0.08, "triangle"); break;
      case "error": toast(m.message, true); st.textContent = m.message; break;
      case "done": ws.close(); break;
    }
  };
  function finish() { state.busy = false; btn.disabled = false; btn.classList.remove("working"); }
}
async function cryptoRun(mode) {
  const pass = $("#c-pass").value, text = $("#c-text").value;
  if (!pass) { toast("enter a password", true); return; }
  if (!text.trim()) { toast("nothing to " + mode, true); return; }
  try {
    const r = await post(`/api/crypto/${mode}`, mode === "encrypt" ? { text, password: pass } : { token: text, password: pass });
    $("#c-out").value = r.token || r.text; beep(760, 0.08);
  } catch (e) { toast(e.message, true); }
}

// ---------------------------------------------------------------- health
async function runHealth() {
  const el = $("#health"); el.innerHTML = `<p class="hint">Sampling every source, this takes a few seconds…</p>`;
  try {
    const h = await api("/api/health");
    el.innerHTML = Object.entries(h).map(([k, r]) => {
      const s = state.meta.sources.find(x => x.key === k);
      if (!r.ok) return `<div class="card"><div class="label"><i class="ti ${s.icon}"></i> ${s.label}</div><div class="value" style="color:var(--bad);font-size:16px">offline</div><div class="sub">${r.error}</div></div>`;
      const col = r.score >= 90 ? "var(--ok)" : r.score >= 70 ? "var(--accent)" : r.score >= 40 ? "var(--warn)" : "var(--bad)";
      return `<div class="card"><div class="label"><i class="ti ${s.icon}"></i> ${s.label}</div><div class="value" style="color:${col}">${r.score}<small style="font-size:12px;color:var(--muted)"> /100 ${r.verdict}</small></div>
        <div class="gauge"><span style="width:${r.score}%;background:${col}"></span></div>
        <div class="sub mono">entropy ${r.shannon_bits_per_byte} b/B · ones ${(r.monobit_ones * 100).toFixed(1)}%<br>χ² ${r.chi_square} · runs z ${r.runs_z}<br>serial corr ${r.serial_correlation} · zip ${r.compression_ratio}</div>
        <div class="sub">${r.detail || ""}</div></div>`;
    }).join("");
  } catch (e) { el.innerHTML = `<p class="hint">${e.message}</p>`; }
}

// ---------------------------------------------------------------- trophies
async function loadTrophies() {
  const t = await api("/api/trophies");
  const cm = t.closest_miss;
  $("#trophies").innerHTML = `
    <div class="card"><i class="ti ti-ticket big"></i><div class="label">Tickets generated</div><div class="value">${t.tickets}</div><div class="sub">${t.shadow_tickets} shadow</div></div>
    <div class="card"><i class="ti ti-target big"></i><div class="label">Tickets with any match</div><div class="value">${t.any_match}</div><div class="sub">of ${t.checked} checked</div></div>
    <div class="card"><i class="ti ti-flame big"></i><div class="label">Current match streak</div><div class="value">${t.current_streak}</div><div class="sub">consecutive checked tickets with a hit</div></div>
    <div class="card"><i class="ti ti-binary big"></i><div class="label">Entropy consumed</div><div class="value">${t.bits_consumed.toLocaleString()}</div><div class="sub">bits of raw noise</div></div>
    <div class="card"><i class="ti ti-star big"></i><div class="label">Favorite source</div><div class="value" style="font-size:18px">${t.favorite_source || "—"}</div><div class="sub">${Object.entries(t.source_counts).map(([k, v]) => k + " " + v).join(" · ")}</div></div>
    <div class="card"><i class="ti ti-award big"></i><div class="label">Closest miss</div><div class="value" style="font-size:16px">${cm ? fmtNums(cm.game, cm.main, cm.bonus, cm.main.filter(n => (cm.result_main || []).includes(n)), !!cm.match_bonus) : "—"}</div><div class="sub">${cm ? `${gameByKey(cm.game)?.name || cm.game} ${cm.checked_date}: ${cm.prize}` : "check some tickets first"}</div></div>`;
}

init().catch(e => { console.error(e); toast("failed to load: " + e.message, true); });
})();
