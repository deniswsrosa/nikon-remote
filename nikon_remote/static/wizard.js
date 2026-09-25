"use strict";
/* Full-screen mic setup wizard for a Mackie ProFX6v3 (Mic/Line 1).
   Depends on app.js globals: S, send, $, $$, el, toast, stripSvg, escapeHtml. */

const W = {
  open: false,
  step: 0,
  mic: null,            // "dynamic" | "condenser" | "unsure"
  ticks: new Set(),
  okSince: 0,           // when the GAIN hint last became "ok"
  script: "",
  reading: null,        // null | "countdown" | "recording" | "analysing"
  first: null,          // first analysis
  report: null,         // latest analysis
  changeIdx: 0,
  verify: null,         // comparison after the check
};

const STEPS = ["Welcome", "Mic position", "Start position", "Set GAIN", "Read the script", "Adjust", "Check", "Recording software"];

/* ---------------- drawing helpers ---------------- */
function bigKnobSvg(curDb, targetDb, title) {
  // ProFX EQ knob: 7 o'clock = −15 dB, 12 = flat (centre click), 5 o'clock = +15 dB; each hour ≈ 3 dB
  const cx = 130, cy = 130, r = 62;
  const deg = (db) => (Math.max(-15, Math.min(15, db)) / 15) * 150;
  const pt = (d, rr) => [cx + rr * Math.sin((d * Math.PI) / 180), cy - rr * Math.cos((d * Math.PI) / 180)];
  let g = `<svg viewBox="0 0 260 270" xmlns="http://www.w3.org/2000/svg">`;
  // hour marks 7 … 12 … 5
  const hours = [7, 8, 9, 10, 11, 12, 1, 2, 3, 4, 5];
  hours.forEach((h, i) => {
    const d = -150 + i * 30;
    const [x1, y1] = pt(d, r + 6), [x2, y2] = pt(d, r + (h === 12 ? 18 : 13)), [tx, ty] = pt(d, r + 30);
    g += `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${h === 12 ? "#e9ebee" : "#5b616b"}" stroke-width="${h === 12 ? 3 : 2}"/>`;
    g += `<text x="${tx}" y="${ty + 4}" font-size="12" fill="#9aa1ab" text-anchor="middle" font-weight="600">${h}</text>`;
  });
  const [lx, ly] = pt(-150, r + 48), [hx, hy] = pt(150, r + 48);
  g += `<text x="${lx + 6}" y="${ly}" font-size="11" fill="#6b727d" text-anchor="middle">−15</text><text x="${hx - 6}" y="${hy}" font-size="11" fill="#6b727d" text-anchor="middle">+15</text>`;
  // target marker
  if (targetDb != null) {
    const [ax, ay] = pt(deg(targetDb), r + 6), [bx, by] = pt(deg(targetDb) - 7, r + 22), [ccx, ccy] = pt(deg(targetDb) + 7, r + 22);
    g += `<polygon points="${ax},${ay} ${bx},${by} ${ccx},${ccy}" fill="#f5a524"/>`;
    // sweep arc from current to target
    if (Math.abs(targetDb - curDb) > 0.5) {
      const a0 = Math.min(deg(curDb), deg(targetDb)), a1 = Math.max(deg(curDb), deg(targetDb));
      const [sx, sy] = pt(a0, r - 12), [ex, ey] = pt(a1, r - 12);
      g += `<path d="M${sx} ${sy} A ${r - 12} ${r - 12} 0 0 1 ${ex} ${ey}" fill="none" stroke="#f5a524" stroke-width="4" stroke-linecap="round" opacity=".55"/>`;
    }
  }
  g += `<circle cx="${cx}" cy="${cy}" r="${r - 4}" fill="#23262c" stroke="#3a3f48" stroke-width="2"/>`;
  const ptr = (d, color, w) => { const [x, y] = pt(d, r - 10); return `<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" stroke="${color}" stroke-width="${w}" stroke-linecap="round"/>`; };
  if (targetDb != null && Math.abs(targetDb - curDb) > 0.5) g += ptr(deg(curDb), "#6b727d", 6) + ptr(deg(targetDb), "#f5a524", 7);
  else g += ptr(deg(curDb), "#e9ebee", 7);
  g += `<circle cx="${cx}" cy="${cy}" r="7" fill="#15171b"/>`;
  g += `<text x="${cx}" y="262" font-size="15" fill="#e9ebee" text-anchor="middle" font-weight="800">${title}</text>`;
  return g + `</svg>`;
}

function switchSvg(label, isIn) {
  return `<svg viewBox="0 0 260 200" xmlns="http://www.w3.org/2000/svg">
    <rect x="70" y="50" width="120" height="60" rx="12" fill="${isIn ? "#f5a52466" : "#23262c"}" stroke="#f5a524" stroke-width="4"/>
    <text x="130" y="89" font-size="24" fill="${isIn ? "#ffd690" : "#9aa1ab"}" text-anchor="middle" font-weight="900">${isIn ? "IN" : "OUT"}</text>
    <text x="130" y="150" font-size="18" fill="#e9ebee" text-anchor="middle" font-weight="800">${label}</text></svg>`;
}

function gainSvg(direction) {
  const cw = direction.startsWith("clockwise");
  return `<svg viewBox="0 0 260 270" xmlns="http://www.w3.org/2000/svg">
    <circle cx="130" cy="130" r="58" fill="#23262c" stroke="#3a3f48" stroke-width="2"/>
    <line x1="130" y1="130" x2="130" y2="80" stroke="#e9ebee" stroke-width="7" stroke-linecap="round"/>
    <path d="M ${cw ? "95 55" : "165 55"} A 90 90 0 0 ${cw ? 1 : 0} ${cw ? "205 95" : "55 95"}" fill="none" stroke="#f5a524" stroke-width="6" stroke-linecap="round"/>
    <polygon points="${cw ? "205,95 190,78 214,76" : "55,95 70,78 46,76"}" fill="#f5a524"/>
    <text x="130" y="236" font-size="15" fill="#e9ebee" text-anchor="middle" font-weight="800">GAIN</text>
    <text x="130" y="256" font-size="12" fill="#9aa1ab" text-anchor="middle">${cw ? "clockwise = louder" : "counter-clockwise = quieter"}</text></svg>`;
}

function distanceSvg(expect) {
  const closer = expect === "up";
  return `<svg viewBox="0 0 260 200" xmlns="http://www.w3.org/2000/svg">
    <circle cx="70" cy="90" r="34" fill="#23262c" stroke="#9aa1ab" stroke-width="2"/>
    <text x="70" y="96" font-size="14" fill="#9aa1ab" text-anchor="middle">you</text>
    <rect x="${closer ? 150 : 190}" y="70" width="44" height="40" rx="10" fill="#23262c" stroke="#f5a524" stroke-width="3"/>
    <text x="${closer ? 172 : 212}" y="96" font-size="12" fill="#f5a524" text-anchor="middle" font-weight="800">MIC</text>
    <path d="M ${closer ? "215 140 L 140 140" : "120 140 L 200 140"}" stroke="#f5a524" stroke-width="4"/>
    <polygon points="${closer ? "140,140 154,132 154,148" : "200,140 186,132 186,148"}" fill="#f5a524"/>
    <text x="130" y="178" font-size="15" fill="#e9ebee" text-anchor="middle" font-weight="800">${closer ? "2–3 cm closer" : "3–5 cm further"}</text></svg>`;
}

// gauge of a measurement against the typical range, with an optional "before" marker
function gaugeSvg(value, range, before) {
  const lo = Math.min(range[0] - 10, value - 3, before ?? value), hi = Math.max(range[1] + 10, value + 3, before ?? value);
  const x = (v) => 10 + ((v - lo) / (hi - lo)) * 280;
  let g = `<svg viewBox="0 0 300 46" xmlns="http://www.w3.org/2000/svg">`;
  g += `<rect x="10" y="14" width="280" height="10" rx="5" fill="#08090a"/>`;
  g += `<rect x="${x(range[0])}" y="12" width="${x(range[1]) - x(range[0])}" height="14" rx="3" fill="#33c46b33" stroke="#33c46b" stroke-width="1.5"/>`;
  if (before != null) g += `<circle cx="${x(before)}" cy="19" r="5" fill="none" stroke="#9aa1ab" stroke-width="2"/>`;
  g += `<circle cx="${x(value)}" cy="19" r="7" fill="#f5a524" stroke="#0b0c0e" stroke-width="2"/>`;
  g += `<text x="${x(range[0])}" y="42" font-size="10" fill="#33c46b" text-anchor="middle">${range[0]}</text><text x="${x(range[1])}" y="42" font-size="10" fill="#33c46b" text-anchor="middle">${range[1]}</text>`;
  return g + `</svg>`;
}

const METRIC_HELP = {
  boom: "Energy at 125–200 Hz vs 315–500 Hz. Mostly set by how close you are to the mic.",
  air: "Energy at 10–16 kHz vs 2–4 kHz. The HI knob changes this (a little).",
  sibilance: "‘s’ and ‘sh’ energy at 5–8 kHz. Tilting the mic off-axis reduces it.",
  boxy: "250–500 Hz ‘room/box’ sound. More distance or a softer room reduces it.",
  presence: "2–4 kHz clarity. Pointing the mic at your mouth increases it.",
};
const VERDICT = { ok: "within the typical range", low: "below the typical range", high: "above the typical range" };

/* ---------------- shell ---------------- */
function wizardOpen() {
  W.open = true;
  if (!W.script) send("voice_script").then((r) => { W.script = r.script; wizRender(); }).catch(() => {});
  let root = $("#wiz");
  if (!root) { root = el("div", { class: "wiz", id: "wiz" }); document.body.append(root); }
  root.hidden = false;
  wizRender();
}
function wizardClose() {
  W.open = false;
  const root = $("#wiz");
  if (root) root.hidden = true;
  if (W.reading === "recording") send("voice_stop").catch(() => {});
}
window.wizardOpen = wizardOpen;

function wizGo(step) { W.step = Math.max(0, Math.min(STEPS.length - 1, step)); wizRender(); $("#wiz .wiz-main").scrollTop = 0; }

function wizRender() {
  const root = $("#wiz");
  if (!root || !W.open) return;
  root.innerHTML = "";
  const prog = el("div", { class: "wiz-progress" });
  STEPS.forEach((_, i) => prog.append(el("span", { class: i < W.step ? "done" : i === W.step ? "on" : "" })));
  const close = el("button", { class: "icon-btn", title: "Close (Esc)" }, icon("i-x"));
  close.addEventListener("click", wizardClose);
  root.append(el("div", { class: "wiz-head" }, el("h1", { text: "Mic setup · Mackie ProFX6v3" }), prog,
    el("span", { class: "wiz-steplabel", text: `Step ${W.step + 1} of ${STEPS.length}: ${STEPS[W.step]}` }), close));
  const main = el("div", { class: "wiz-main" }), side = el("div", { class: "wiz-side" });
  root.append(el("div", { class: "wiz-body" }, main, side));
  const foot = el("div", { class: "wiz-foot" });
  root.append(foot);
  renderSide(side);
  [stepWelcome, stepMic, stepStart, stepGain, stepRead, stepAdjust, stepCheck, stepSoftware][W.step](main, foot);
  wizAudio(S.audio);
}

function footButtons(foot, { back = true, next = null, nextLabel = "Next", nextDisabled = false, extra = null } = {}) {
  const left = el("div"), right = el("div", { style: "display:flex;gap:10px" });
  if (back && W.step > 0) { const b = el("button", { class: "btn", text: "Back" }); b.addEventListener("click", () => wizGo(W.step - 1)); left.append(b); }
  if (extra) right.append(extra);
  if (next) { const n = el("button", { class: "btn btn-accent", text: nextLabel }); n.disabled = nextDisabled; n.addEventListener("click", next); n.id = "wizNext"; right.append(n); }
  foot.append(left, right);
}

/* ---------------- side panel: live level ---------------- */
function renderSide(side) {
  side.append(el("div", { class: "lvl" },
    el("div", { class: "lvl-title" }, el("span", { text: "Your voice level" }), el("span", { id: "wLvlVal", text: "–" })),
    el("div", { class: "lvl-track" }, el("div", { class: "lvl-zone", style: `left:${pctDb(-12)}%;width:${pctDb(-6) - pctDb(-12)}%` }), el("div", { class: "lvl-now", id: "wLvlNow" }), el("div", { class: "lvl-needle", id: "wLvlNeedle", style: "left:0%" })),
    el("div", { class: "lvl-scale", html: "<span>−40</span><span>−30</span><span>−20</span><span>−12</span><span>−6</span><span>0 dBFS</span>" }),
    el("div", { class: "lvl-read" }, el("span", { html: `Loudness <b id="wLufs">–</b>` }), el("span", { html: `Noise floor <b id="wFloor">–</b>` }))));
  side.append(el("div", { class: "hint-big", id: "wHint" }, el("div", { class: "arrow", text: "…" }), el("div", { class: "t", text: "" }), el("div", { class: "s", text: "" })));
  side.append(el("div", { class: "side-note", html: "The <b>orange needle</b> is your speech peaks over the last 10 seconds of talking — it moves slowly on purpose, so one loud or soft sentence doesn't change the advice. The <b>green zone</b> (−12 to −6 dBFS) is the target." }));
}
const pctDb = (v) => Math.max(0, Math.min(100, ((v + 40) / 40) * 100));

function wizAudio(a) {
  if (!W.open || !a) return;
  const h = a.gain_hint || {};
  const now = $("#wLvlNow"), needle = $("#wLvlNeedle");
  if (!now) return;
  now.style.width = pctDb(a.peak ?? -120) + "%";
  if (h.p90 != null) needle.style.left = pctDb(h.p90) + "%";
  $("#wLvlVal").textContent = h.p90 != null ? `peaks ${h.p90.toFixed(0)} dBFS` : "–";
  $("#wLufs").textContent = a.lufs_s != null && a.lufs_s > -70 ? `${a.lufs_s.toFixed(0)} LUFS` : "–";
  $("#wFloor").textContent = a.floor != null ? `${a.floor.toFixed(0)} dB` : "–";
  const box = $("#wHint");
  let cls = "", arrow = "…", t = "Talk at your recording volume", s = "Read the script out loud, as you will on camera.";
  if (a.error) { cls = "bad"; arrow = "!"; t = "No sound from the mixer"; s = a.error; }
  else if (a.clipping) { cls = "bad"; arrow = "↺"; t = "Clipping — turn GAIN down"; s = "Counter-clockwise (left), a little at a time."; }
  else if (h.action === "listening") { t = "Keep talking…"; s = `Measuring — ${Math.max(0, 4 - h.speech_s).toFixed(0)} more seconds of speech needed.`; }
  else if (h.action === "up") { cls = "up"; arrow = "↻"; t = `Turn GAIN clockwise (right)`; s = `About +${h.db} dB — a small amount at a time, keep reading, then wait for the needle to settle.`; }
  else if (h.action === "down") { cls = "down"; arrow = "↺"; t = `Turn GAIN counter-clockwise (left)`; s = `About ${h.db} dB — a small amount at a time, keep reading, then wait for the needle to settle.`; }
  else if (h.action === "ok") { cls = "ok"; arrow = "✓"; t = "Level is right — leave GAIN"; s = "The needle is in the green zone."; }
  box.className = "hint-big " + cls;
  $(".arrow", box).textContent = arrow; $(".t", box).textContent = t; $(".s", box).textContent = s;
  // step 4: enable Next after 5 s continuously OK
  if (W.step === 3) {
    if (h.action === "ok") { if (!W.okSince) W.okSince = performance.now(); } else W.okSince = 0;
    const nb = $("#wizNext");
    if (nb) {
      const held = W.okSince ? (performance.now() - W.okSince) / 1000 : 0;
      nb.disabled = held < 5;
      nb.textContent = held >= 5 ? "Level is right — next" : held > 0 ? `Hold it… ${Math.ceil(5 - held)} s` : "Waiting for the green zone";
    }
  }
  const cd = $("#wRecLeft");
  if (cd && a.checking) cd.textContent = `${Math.ceil(a.check_left)} s left (stop any time after you finish reading)`;
}

/* ---------------- steps ---------------- */
function stepWelcome(main, foot) {
  main.append(el("h2", { text: "Let's set up your voice" }),
    el("p", { class: "lead", html: "About 5 minutes. You'll set the <b>Mic/Line 1</b> channel on your ProFX6v3 one control at a time, read the same short passage a few times, and the app measures your voice and tells you exactly what to move — then checks that it worked." }),
    el("div", { class: "tip-cards" },
      tipCard("1", "Sit exactly where you'll record", "Same chair, same distance to the mic, same room lights and fans."),
      tipCard("2", "Headphones on", "So the speakers don't leak into the mic while you test."),
      tipCard("3", "Quiet room", "Turn off fans and AC for the test if you can — the app also measures background noise."),
      tipCard("4", "Read in your recording voice", "The same energy you use on camera. Don't whisper, don't shout.")));
  footButtons(foot, { next: () => wizGo(1), nextLabel: "Start" });
}
function tipCard(n, t, d) { return el("div", { class: "tip-card" }, el("div", { class: "big", text: n }), el("b", { text: t }), el("p", { text: d })); }

function stepMic(main, foot) {
  main.append(el("h2", { text: "What kind of mic is it?" }), el("p", { class: "lead", text: "It decides the 48V switch and how far from the mic you should sit." }));
  const row = el("div", { class: "choice-row" });
  for (const [k, t, d] of [["dynamic", "Dynamic", "e.g. Shure SM7B / SM58, Rode PodMic, Samson Q2U"], ["condenser", "Condenser", "e.g. Rode NT1, AT2020, most studio 'large diaphragm' mics"], ["unsure", "Not sure", "Tell me the model later — start as dynamic"]]) {
    const c = el("button", { class: "choice" + (W.mic === k ? " on" : "") }, el("b", { text: t }), el("span", { text: d }));
    c.addEventListener("click", () => { W.mic = k; wizRender(); });
    row.append(c);
  }
  main.append(row);
  if (W.mic) {
    const cond = W.mic === "condenser";
    main.append(el("div", { class: "tip-cards" },
      tipCard(cond ? "15–20 cm" : "5–10 cm", "Distance to your mouth", cond ? "About a hand span. Closer gets boomy and picks up breaths." : "About a fist to a hand's width. Dynamic mics need you close."),
      tipCard("↗", "Slightly off-axis", "Point the mic at the corner of your mouth, not straight into it — fewer pops and softer ‘s’ sounds."),
      tipCard(cond ? "48V ON" : "48V OFF", "Phantom power switch", cond ? "Condenser mics need it (master section of the mixer)." : "Dynamic mics don't need it. Leave it off."),
      tipCard("◯", "Pop filter / foam", "Recommended, especially for ‘p’ and ‘b’ sounds.")));
  }
  footButtons(foot, { next: () => wizGo(2), nextDisabled: !W.mic });
}

const START_ITEMS = [
  ["gain", "GAIN", "About 9 o'clock for now — you'll set it in the next step."],
  ["low_cut", "LOW CUT", "Pressed IN. It removes rumble below 100 Hz — always on for a voice."],
  ["hi", "HI", "12 o'clock — the centre click (flat)."],
  ["low", "LOW", "12 o'clock — the centre click (flat). On this mixer it barely affects a voice; you'll leave it there."],
  ["fx", "FX", "OUT — no reverb on a voice."],
  ["stereo_pan", "STEREO PAN", "OUT. If it's IN, channel 1 plays only on the left."],
  ["level", "LEVEL", "On the U mark (unity). This knob changes the recording; MAIN MIX doesn't."],
];
function stepStart(main, foot) {
  main.append(el("h2", { text: "Set channel 1 to the starting position" }),
    el("p", { class: "lead", html: "Top to bottom on the <b>Mic/Line 1</b> strip. Tick each one as you set it." }));
  const badges = {}; START_ITEMS.forEach(([k], i) => (badges[k] = i + 1));
  const list = el("ul", { class: "tick-list" });
  START_ITEMS.forEach(([k, ctl, d], i) => {
    const li = el("li", { class: W.ticks.has(k) ? "done" : "" }, el("span", { class: "box", text: W.ticks.has(k) ? "✓" : "" }),
      el("div", {}, el("span", { class: "n", text: String(i + 1) }), el("b", { text: ctl }), el("span", { class: "d", text: d })));
    li.addEventListener("click", () => { W.ticks.has(k) ? W.ticks.delete(k) : W.ticks.add(k); wizRender(); });
    list.append(li);
  });
  main.append(el("div", { class: "checklist-grid" }, el("div", { html: stripSvg({ low_cut: true, hi: 0, low: 0, fx: false, stereo_pan: false }, null, badges) }), list));
  const all = START_ITEMS.every(([k]) => W.ticks.has(k));
  footButtons(foot, {
    next: async () => { try { S.mixer.state = await send("mixer_state", { low_cut: true, low: 0, hi: 0 }); } catch {} wizGo(3); },
    nextDisabled: !all, nextLabel: all ? "Next" : `Tick all ${START_ITEMS.length}`,
  });
}

function stepGain(main, foot) {
  W.okSince = 0;
  main.append(el("h2", { text: "Set GAIN while you read" }),
    el("p", { class: "lead", html: "Read the passage below out loud, in your recording voice, and <b>keep reading</b>. Watch the right-hand panel: turn <b>GAIN</b> a little at a time in the direction it shows, then keep reading while the needle settles (it averages 10 seconds on purpose). When it says ‘Level is right’ for 5 seconds, you're done. Loop back to the start of the passage if you reach the end." }),
    el("div", { class: "script", text: W.script || "Loading the script…" }));
  footButtons(foot, { next: () => wizGo(4), nextLabel: "Waiting for the green zone", nextDisabled: true,
    extra: (() => { const b = el("button", { class: "btn", text: "Skip" }); b.addEventListener("click", () => wizGo(4)); return b; })() });
}

async function startReading(isVerify) {
  W.reading = "countdown"; wizRender();
  for (const n of [3, 2, 1]) { const c = $("#wCount"); if (c) c.textContent = n; await new Promise((r) => setTimeout(r, 800)); }
  W.reading = "recording"; wizRender();
  try {
    const r = await send("voice_check", 75);
    W.reading = null;
    if (r.error) { toast(r.error, "error"); wizRender(); return; }
    if (isVerify) { W.verify = compareReports(W.report, r); W.report = r; }
    else { W.first = r; W.report = r; W.changeIdx = 0; }
    S.mixer.report = r;
    wizGo(isVerify ? 6 : 5);
  } catch (e) { W.reading = null; toast(e.message, "error"); wizRender(); }
}

function readingBlock(main, isVerify) {
  const status = el("div", { class: "rec-status" });
  if (W.reading === "countdown") status.append(el("span", { class: "countdown", id: "wCount", text: "3" }), el("span", { text: "Get ready to read…" }));
  else if (W.reading === "recording") {
    const stop = el("button", { class: "btn btn-accent", text: "I've finished reading" });
    stop.addEventListener("click", () => { send("voice_stop").catch(() => {}); W.reading = "analysing"; wizRender(); });
    status.append(el("span", { class: "rec-dot2" }), el("b", { text: "Listening — read the whole passage" }), el("span", { id: "wRecLeft", class: "side-note" }), stop);
  } else if (W.reading === "analysing") status.append(el("div", { class: "spinner" }), el("b", { text: "Analysing your voice…" }));
  else {
    const go = el("button", { class: "btn btn-accent", style: "height:46px;font-size:16px;padding:0 24px", text: isVerify ? "Start reading again" : "Start reading" });
    go.addEventListener("click", () => startReading(isVerify));
    status.append(go, el("span", { class: "side-note", text: "A 3-second countdown, then read at your normal pace. Takes about 40 seconds." }));
  }
  main.append(status, el("div", { class: "script" + (W.reading === "recording" ? " reading" : ""), text: W.script || "Loading…" }));
}

function stepRead(main, foot) {
  main.append(el("h2", { text: "Read the passage" }),
    el("p", { class: "lead", html: "This is the <b>Rainbow Passage</b>, a standard text used in speech science because it contains all the sounds of spoken English. Reading the <b>same words every time</b> makes the measurements comparable — so changes you see come from the mixer, not from what you said." }));
  readingBlock(main, false);
  footButtons(foot, {});
}

function gaugeCards(report, before) {
  const wrap = el("div");
  wrap.append(el("div", { class: "gauge-legend", html: `<span><i style="background:#f5a524"></i>${before ? "this reading" : "your voice"}</span>` +
    (before ? `<span><i style="border:2px solid #9aa1ab"></i>first reading</span>` : "") + `<span><i style="background:#33c46b55;border-radius:3px;border:1px solid #33c46b"></i>typical range</span>` }));
  const box = el("div", { class: "gauges" });
  wrap.append(box);
  const lvl = report.level;
  box.append(el("div", { class: "gauge" },
    el("div", { class: "g-top" }, el("span", { class: "g-label", text: "Level (speech peaks)" }), el("span", { class: "g-verdict " + (lvl.peak_p90 < -12 ? "low" : lvl.peak_p90 > -6 ? "high" : "ok"), text: `${lvl.peak_p90} dBFS` })),
    el("div", { html: gaugeSvg(lvl.peak_p90, [-12, -6], before ? before.level.peak_p90 : null) }),
    el("div", { class: "g-sub", text: `Target −12 … −6 dBFS. Average level ${lvl.rms} dBFS (ideal about −18).` })));
  for (const [k, g] of Object.entries(report.gauges)) {
    box.append(el("div", { class: "gauge" },
      el("div", { class: "g-top" }, el("span", { class: "g-label", text: g.label }), el("span", {}, el("span", { class: "g-val", text: `${g.value > 0 ? "+" : ""}${g.value} dB` }), el("span", { class: "g-verdict " + g.verdict, text: VERDICT[g.verdict] }))),
      el("div", { html: gaugeSvg(g.value, g.range, before ? before.gauges[k].value : null) }),
      el("div", { class: "g-sub", text: METRIC_HELP[k] || "" })));
  }
  return wrap;
}

function stepAdjust(main, foot) {
  const r = W.report;
  if (!r) { wizGo(4); return; }
  const steps = r.steps || [];
  main.append(el("h2", { text: steps.length ? "Make these changes, one at a time" : "Nothing to change" }),
    el("p", { class: "lead", html: `Your voice compared with <b>${escapeHtml(r.range_name)}</b> (green zone). The orange dot is you.` }),
    gaugeCards(r, null));
  if (!steps.length) {
    main.append(el("p", { class: "success", text: "Your channel is set — level and tone are within range." }));
    notesBlock(main, r);
    footButtons(foot, { next: () => wizGo(7), nextLabel: "Recording software settings" });
    return;
  }
  const idx = Math.min(W.changeIdx, steps.length - 1), st = steps[idx];
  const chips = el("div", { class: "change-list" });
  steps.forEach((s, i) => chips.append(el("span", { class: i < idx ? "done" : i === idx ? "on" : "", text: `${i + 1}. ${s.control}` })));
  main.append(chips, changeCard(st, idx + 1, steps.length));
  notesBlock(main, r);
  const last = idx === steps.length - 1;
  footButtons(foot, {
    next: async () => {
      if (!last) { W.changeIdx++; wizRender(); return; }
      try { S.mixer.state = await send("mixer_state", { low_cut: true, low: 0, hi: r.recommended.hi }); } catch {}
      S.mixer.applied = true;
      wizGo(6);
    },
    nextLabel: last ? "Done — check it" : "Done — next change",
  });
}

function changeCard(st, n, total) {
  let visual = "", doText = "", where = "";
  if (st.type === "knob") {
    visual = bigKnobSvg(st.from, st.to, st.control);
    doText = `Turn ${st.control} ${st.direction} to ${st.to_clock}`;
    where = `${st.control === "HI" ? "HI is the first EQ knob below the LOW CUT switch." : "LOW is the second EQ knob, below HI."} Grey line = where it is now, orange = the target (${st.to > 0 ? "+" : ""}${st.to} dB). Each hour on the clock ≈ 3 dB.`;
  } else if (st.type === "gain") {
    visual = gainSvg(st.direction);
    doText = `Turn GAIN ${st.direction}, about ${Math.abs(st.delta)} dB`;
    where = "Do it while reading the passage and watch the needle on the right settle in the green zone.";
  } else if (st.type === "switch") {
    visual = switchSvg(st.control, st.to);
    doText = `Set ${st.control} ${st.to ? "IN (pressed)" : "OUT (released)"}`;
  } else if (st.type === "position") {
    visual = distanceSvg(st.expect);
    doText = st.expect === "up" ? "Move a little closer to the mic" : "Move a little further from the mic";
    where = st.text;
  }
  return el("div", { class: "change-card" }, el("div", { class: "visual", html: visual }),
    el("div", {}, el("div", { class: "what", text: `Change ${n} of ${total} · ${st.control}` }), el("div", { class: "do", text: doText }),
      el("div", { class: "why", text: `Why: ${st.why}.` }), where ? el("div", { class: "where", text: where }) : null));
}

function notesBlock(main, r) {
  if (!r.notes || !r.notes.length) return;
  const ul = el("ul", { class: "notes", style: "font-size:14px;max-width:900px" });
  r.notes.forEach((n) => ul.append(el("li", { text: n })));
  main.append(el("h3", { text: "Things the mixer can't change", style: "margin:22px 0 6px;font-size:16px" }), ul);
}

function compareReports(before, after) {
  const out = [];
  for (const st of before.steps || []) {
    if (st.type === "knob" || st.type === "position") {
      const k = st.metric, b = before.gauges[k].value, a = after.gauges[k].value, d = +(a - b).toFixed(1);
      const expect = st.type === "knob" ? st.expected_shift : st.expect === "up" ? 2 : -2;
      const good = Math.sign(d) === Math.sign(expect) && Math.abs(d) >= Math.abs(expect) * 0.4;
      const inRange = after.gauges[k].verdict === "ok";
      out.push({ ok: good || inRange, title: `${st.control}: ${before.gauges[k].label} ${b} → ${a} dB`,
        sub: good ? `Moved as expected (${d > 0 ? "+" : ""}${d} dB, expected about ${expect > 0 ? "+" : ""}${expect}).`
          : inRange ? "Now within the typical range."
          : Math.abs(d) < 0.5 ? `Barely changed (${d} dB). ${st.type === "knob" ? `Check you turned ${st.control} (${st.control === "HI" ? "first EQ knob below LOW CUT" : "second EQ knob"}) to ${st.to_clock}.` : "Did the distance change? Keep the new distance while reading."}`
          : `Went the other way (${d > 0 ? "+" : ""}${d} dB). ${st.type === "knob" ? `Turn ${st.control} ${st.direction}.` : ""}` });
    } else if (st.type === "gain") {
      const p = after.level.peak_p90;
      out.push({ ok: p >= -12 && p <= -6, title: `GAIN: speech peaks ${before.level.peak_p90} → ${p} dBFS`, sub: p >= -12 && p <= -6 ? "In the target zone." : "Still outside −12…−6 — adjust GAIN with the live needle." });
    } else if (st.type === "switch") {
      const okSw = st.key === "stereo_pan" ? Math.abs(after.balance) <= 6 : true;
      out.push({ ok: okSw, title: `${st.control}`, sub: okSw ? "Looks right." : "Voice still on one side — the STEREO PAN switch is still IN." });
    }
  }
  return out;
}

function stepCheck(main, foot) {
  main.append(el("h2", { text: "Check that it worked" }),
    el("p", { class: "lead", text: "Read the same passage again. The app compares it with your first reading, control by control." }));
  if (W.verify) {
    const ul = el("ul", { class: "verify-list" });
    W.verify.forEach((v) => ul.append(el("li", { class: v.ok ? "ok" : "warn" }, el("span", { class: "ic", text: v.ok ? "✓" : "!" }), el("div", {}, el("b", { text: v.title }), el("span", { class: "sub", text: v.sub })))));
    main.append(ul);
    const remaining = (W.report.steps || []).length;
    if (!remaining && W.verify.every((v) => v.ok)) main.append(el("p", { class: "success", text: "All set — your mixer is dialled in." }));
    else if (remaining) main.append(el("p", { class: "lead", html: `The new reading still suggests <b>${remaining}</b> change${remaining > 1 ? "s" : ""}.` }));
    main.append(gaugeCards(W.report, W.first));
    const again = el("button", { class: "btn", text: remaining ? "Adjust again" : "Read again" });
    again.addEventListener("click", () => { if (remaining) { W.changeIdx = 0; wizGo(5); } else { W.verify = null; wizRender(); } });
    footButtons(foot, { next: () => wizGo(7), nextLabel: "Recording software settings", extra: again });
    return;
  }
  readingBlock(main, true);
  footButtons(foot, {});
}

function stepSoftware(main, foot) {
  const r = W.report || S.mixer.report;
  main.append(el("h2", { text: "Recording software (OBS)" }),
    el("p", { class: "lead", html: "The ProFX6v3 has no compressor, so the podcast ‘evenness’ comes from these filters. In OBS: right-click your mic source → <b>Filters</b> → add them <b>in this order</b>. They were simulated on your own voice to land at −16 LUFS." }));
  if (r && r.software) {
    const sw = r.software, c = sw.compressor, g = sw.noise_gate;
    const t = el("table", { class: "obs-table" });
    const row = (a, b) => t.append(el("tr", {}, el("td", { text: a }), el("td", { text: b })));
    const head = (a) => t.append(el("tr", { class: "h" }, el("td", { colspan: "2", text: a })));
    if (g) { head("1. Noise Gate"); row("Close threshold", `${g.close_db} dB`); row("Open threshold", `${g.open_db} dB`); row("Attack / Hold / Release", `${g.attack_ms} / ${g.hold_ms} / ${g.release_ms} ms`); }
    head(`${g ? 2 : 1}. Compressor`); row("Ratio", `${c.ratio}:1`); row("Threshold", `${c.threshold_db} dB`); row("Attack", `${c.attack_ms} ms`); row("Release", `${c.release_ms} ms`); row("Output Gain", `${c.output_gain_db >= 0 ? "+" : ""}${c.output_gain_db} dB`);
    head(`${g ? 3 : 2}. Limiter`); row("Threshold", `${sw.limiter.threshold_db} dB`); row("Release", `${sw.limiter.release_ms} ms`);
    main.append(t, el("p", { class: "side-note", style: "margin-top:12px", text: `Predicted result on your voice: ${sw.predicted.loudness} LUFS, peaks ${sw.predicted.peak} dBFS. For YouTube, normalise to −14 LUFS when you edit.` }));
  } else main.append(el("p", { class: "lead", text: "Read the passage first (step 5) to get settings computed for your voice." }));
  const done = el("button", { class: "btn btn-accent", text: "Finish" });
  done.addEventListener("click", () => { wizardClose(); toast("Mic setup saved", "ok"); renderAll(); });
  footButtons(foot, { extra: done });
}

document.addEventListener("keydown", (e) => { if (W.open && e.key === "Escape") { e.stopPropagation(); wizardClose(); } }, true);
