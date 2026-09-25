"use strict";

/* ======================================================================
   State
   ====================================================================== */
const S = {
  catalog: null,          // {sections, settings}
  names: {},              // code -> PTP name
  props: {},              // code -> {v, w, dt, form, vals, min, max, step}
  status: {},
  byKey: {},              // setting key -> setting
  byCode: {},             // code -> setting
  header: null,           // latest live view header
  face: null,             // latest face analysis
  audio: {},              // latest audio levels
  session: {},            // battery/disk estimates
  assist: null,           // assistant settings (face target, record folder, ...)
  voiceReport: null,
  frameSize: { w: 640, h: 424 },
  af: { state: "idle", until: 0 },
  pending: {},            // code -> value being set (optimistic UI)
  selectedDial: 0,
  lastFrameAt: 0,
  ui: loadPrefs(),
};

function loadPrefs() {
  const defaults = { overlays: { grid: false, safe: false, zebra: false, peaking: false, hist: true, level: false, face: true }, tab: "exposure", otherScope: false, zebraLevel: 245, recordOn: "pc", collapsed: {} };
  try {
    const saved = JSON.parse(localStorage.getItem("nikonRemote.ui") || "{}");
    return Object.assign(defaults, saved, { overlays: Object.assign(defaults.overlays, saved.overlays || {}) });
  } catch { return defaults; }
}
function savePrefs() {
  try { localStorage.setItem("nikonRemote.ui", JSON.stringify(S.ui)); } catch {}
}

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") e.className = v;
    else if (k === "text") e.textContent = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (k === "html") e.innerHTML = v;
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null) e.append(kid.nodeType ? kid : document.createTextNode(kid));
  return e;
};
const icon = (id) => {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  const u = document.createElementNS("http://www.w3.org/2000/svg", "use");
  u.setAttribute("href", "#" + id);
  s.append(u);
  return s;
};

/* ======================================================================
   Formatting
   ====================================================================== */
const ISO_NAMES = { 50: "Lo 1", 64: "Lo 0.7", 80: "Lo 0.3", 40000: "Hi 0.3", 51200: "51200", 64000: "Hi 0.3", 81200: "Hi 0.7", 102400: "Hi 1", 204800: "Hi 2", 409600: "Hi 3", 820000: "Hi 4", 1640000: "Hi 5" };

function fmtShutter(v) {
  if (v === 0xffffffff) return "Bulb";
  if (v === 0xfffffffe) return "Time";
  if (v === 0xfffffffd) return "X";
  const num = Math.floor(v / 65536), den = v % 65536;
  if (!den) return String(v);
  if (num === 1) return den === 1 ? '1"' : `1/${den}`;
  const t = num / den;
  if (t >= 1) return `${+t.toFixed(1)}"`;
  return `1/${+(den / num).toFixed(1)}`;
}
function shutterSeconds(v) {
  if (v >= 0xfffffffd) return null;
  const num = Math.floor(v / 65536), den = v % 65536;
  return den ? num / den : null;
}
function fmtEv(v, scale = 1000) {
  const ev = v / scale;
  if (Math.abs(ev) < 0.05) return "±0";
  return (ev > 0 ? "+" : "−") + Math.abs(ev).toFixed(1);
}
function fmtValue(setting, v) {
  if (v === undefined || v === null) return "–";
  const f = setting ? setting.fmt : "raw";
  switch (f) {
    case "shutter": return fmtShutter(v);
    case "aperture": return v ? `f/${+(v / 100).toFixed(1)}` : "–";
    case "iso": return ISO_NAMES[v] || String(v);
    case "ev1000": return fmtEv(v);
    case "kelvin": return `${v} K`;
    case "enum": return (setting.labels && setting.labels[String(v)]) || `#${v}`;
    case "text": return v === "" ? "(empty)" : String(v).trim() || "(blank)";
    default: return String(v);
  }
}
function fmtBytes(n) {
  if (!n && n !== 0) return "–";
  const u = ["B", "KB", "MB", "GB"]; let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(i ? 1 : 0)} ${u[i]}`;
}
function fmtDuration(min) {
  if (min >= 600) return `${Math.round(min / 60)} h`;
  return min >= 90 ? `${Math.floor(min / 60)} h ${String(min % 60).padStart(2, "0")} min` : `${min} min`;
}
function fmtClock(sec) {
  const m = Math.floor(sec / 60), s = sec % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

/* ======================================================================
   Property helpers
   ====================================================================== */
const UNSAFE_CODES = new Set([0xd1f0]);
const BODY_ONLY = "The D7500 only starts recording from its own record button";
const recBlockers = () => (S.status.movie_prohibit || []).filter((r) => r !== BODY_ONLY);
const bodyOnlyRecording = () => (S.status.movie_prohibit || []).includes(BODY_ONLY);
const P = (key) => { const s = S.byKey[key]; return s ? S.props[s.code] : undefined; };
const V = (key) => { const p = P(key); return p ? p.v : undefined; };
const isMovie = () => V("lv_selector") === 1;
const scopeMatches = (s) => s.scope === "both" || (s.scope === "movie") === isMovie();

function choicesOf(p) {
  if (!p) return [];
  let out = [];
  if (p.form === "enum") out = p.vals || [];
  else if (p.form === "range") {
    const step = p.step || 1;
    if ((p.max - p.min) / step > 400) return [];
    for (let x = p.min; x <= p.max; x += step) out.push(x);
  }
  // For labelled settings, a range often includes values the camera rejects: keep the known ones.
  const s = S.byCode[p.code];
  if (s && s.fmt === "enum" && s.labels && p.form === "range") out = out.filter((v) => s.labels[String(v)] !== undefined || v === p.v);
  return out;
}

/* ======================================================================
   WebSocket
   ====================================================================== */
let ws = null, reqId = 0;
const waiting = new Map();

function connect() {
  ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  ws.binaryType = "arraybuffer";
  ws.onmessage = (ev) => (typeof ev.data === "string" ? onJson(JSON.parse(ev.data)) : onFrame(ev.data));
  ws.onclose = () => {
    for (const [, w] of waiting) w.reject(new Error("Connection to the app was lost"));
    waiting.clear();
    setServerDown(true);
    setTimeout(connect, 1000);
  };
  ws.onopen = () => setServerDown(false);
}

function send(op, ...args) {
  return new Promise((resolve, reject) => {
    if (!ws || ws.readyState !== 1) return reject(new Error("Not connected to the app"));
    const id = ++reqId;
    waiting.set(id, { resolve, reject });
    ws.send(JSON.stringify({ op, args, id }));
  });
}

async function run(op, ...args) {
  try {
    return await send(op, ...args);
  } catch (e) {
    toast(e.message, "error");
    throw e;
  }
}

function onJson(msg) {
  switch (msg.type) {
    case "hello": {
      const d = msg.data;
      S.catalog = d.catalog; S.names = d.names;
      S.byKey = {}; S.byCode = {};
      for (const s of d.catalog.settings) { S.byKey[s.key] = s; S.byCode[s.code] = s; }
      S.props = {};
      for (const [c, p] of Object.entries(d.props)) S.props[c] = Object.assign(p, { code: Number(c) });
      S.status = d.status;
      S.face = d.face; S.audio = d.audio || {}; S.session = d.session || {}; S.assist = d.assist;
      buildTabs(); renderAll();
      loadAudioSources();
      loadPresets();
      break;
    }
    case "props":
      for (const [c, p] of Object.entries(msg.data)) {
        const prev = S.props[c];
        S.props[c] = Object.assign(p, { code: Number(c) });
        if (S.pending[c] !== undefined && (p.v === S.pending[c] || !prev || prev.v !== p.v)) delete S.pending[c];
      }
      markChanged(Object.keys(msg.data));
      renderAll();
      break;
    case "status": {
      const keys = Object.keys(msg.data);
      Object.assign(S.status, msg.data);
      // Tabs only depend on a few status fields; don't rebuild them for meter/battery ticks.
      renderAll(keys.some((k) => ["pc_mode", "recording", "lv", "connected"].includes(k)));
      break;
    }
    case "toast":
      toast(msg.data.text, msg.data.level);
      break;
    case "face":
      S.face = msg.data;
      renderFace();
      break;
    case "audio":
      S.audio = msg.data;
      renderAudioLevels();
      break;
    case "session":
      S.session = msg.data;
      renderAll(false);
      break;
    case "result": {
      const w = waiting.get(msg.id);
      if (!w) break;
      waiting.delete(msg.id);
      msg.ok ? w.resolve(msg.data) : w.reject(new Error(msg.error));
      break;
    }
  }
}

/* ======================================================================
   Live view rendering
   ====================================================================== */
const video = $("#video"), overlay = $("#overlay"), viewer = $("#viewer");
const vctx = video.getContext("2d"), octx = overlay.getContext("2d");
const work = document.createElement("canvas"), wctx = work.getContext("2d", { willReadFrequently: true });
const hist = $("#histogram"), hctx = hist.getContext("2d");
let lastBitmap = null, rect = { x: 0, y: 0, w: 0, h: 0 };

function layoutCanvases() {
  const W = viewer.clientWidth, H = viewer.clientHeight, dpr = window.devicePixelRatio || 1;
  const ar = S.frameSize.w / S.frameSize.h;
  let w = W, h = W / ar;
  if (h > H) { h = H; w = H * ar; }
  rect = { x: Math.round((W - w) / 2), y: Math.round((H - h) / 2), w: Math.round(w), h: Math.round(h) };
  for (const c of [video, overlay]) {
    c.style.left = rect.x + "px"; c.style.top = rect.y + "px";
    c.style.width = rect.w + "px"; c.style.height = rect.h + "px";
    c.width = Math.round(rect.w * dpr); c.height = Math.round(rect.h * dpr);
  }
}
new ResizeObserver(() => { layoutCanvases(); drawFrame(); }).observe(viewer);

async function onFrame(buf) {
  const dv = new DataView(buf);
  const hlen = dv.getUint32(0);
  const header = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 4, hlen)));
  const blob = new Blob([new Uint8Array(buf, 4 + hlen)], { type: "image/jpeg" });
  try {
    const bmp = await createImageBitmap(blob);
    if (lastBitmap) lastBitmap.close();
    lastBitmap = bmp;
    S.header = header;
    if (bmp.width !== S.frameSize.w || bmp.height !== S.frameSize.h) {
      S.frameSize = { w: bmp.width, h: bmp.height };
      layoutCanvases();
    }
    S.lastFrameAt = performance.now();
    drawFrame();
    renderViewerState();
    if (header.lv_remaining_s != null && header.lv_remaining_s !== S._lastLvLeft) { S._lastLvLeft = header.lv_remaining_s; renderAll(false); }
  } catch (e) {
    console.warn("bad frame", e);
  } finally {
    if (ws && ws.readyState === 1) ws.send('{"op":"ack"}');
  }
}

function drawFrame() {
  if (!lastBitmap) return;
  vctx.imageSmoothingQuality = "high";
  vctx.drawImage(lastBitmap, 0, 0, video.width, video.height);
  drawOverlay();
}

function analysePixels() {
  // Work on a small copy: fast enough for every frame.
  const ow = Math.min(320, lastBitmap.width), oh = Math.round(ow * lastBitmap.height / lastBitmap.width);
  if (work.width !== ow) { work.width = ow; work.height = oh; }
  wctx.drawImage(lastBitmap, 0, 0, ow, oh);
  return wctx.getImageData(0, 0, ow, oh);
}

function drawOverlay() {
  const W = overlay.width, H = overlay.height, dpr = window.devicePixelRatio || 1;
  octx.clearRect(0, 0, W, H);
  const ov = S.ui.overlays;
  let img = null;
  if (lastBitmap) img = analysePixels();
  if (img) updateDarkNote(img);

  if (img && ov.zebra) drawZebra(img, W, H);
  if (img && ov.peaking) drawPeaking(img, W, H);
  if (img && ov.hist) drawHistogram(img);

  octx.lineWidth = 1 * dpr;
  if (ov.grid) {
    octx.strokeStyle = "rgba(255,255,255,.45)";
    octx.beginPath();
    for (const f of [1 / 3, 2 / 3]) {
      octx.moveTo(W * f, 0); octx.lineTo(W * f, H);
      octx.moveTo(0, H * f); octx.lineTo(W, H * f);
    }
    octx.stroke();
    octx.strokeStyle = "rgba(255,255,255,.7)";
    const c = 10 * dpr;
    octx.beginPath(); octx.moveTo(W / 2 - c, H / 2); octx.lineTo(W / 2 + c, H / 2); octx.moveTo(W / 2, H / 2 - c); octx.lineTo(W / 2, H / 2 + c); octx.stroke();
  }
  if (ov.safe) {
    octx.setLineDash([6 * dpr, 5 * dpr]);
    octx.strokeStyle = "rgba(255,255,255,.5)";
    for (const f of [0.93, 0.9]) {
      const w = W * f, h = H * f;
      octx.strokeRect((W - w) / 2, (H - h) / 2, w, h);
    }
    octx.setLineDash([]);
  }
  if (ov.level) drawLevel(W, H, dpr);
  if (ov.face) drawFace(W, H, dpr);
  drawAfBox(W, H, dpr);
}

function drawFace(W, H, dpr) {
  // eye line target: upper third
  octx.setLineDash([8 * dpr, 6 * dpr]);
  octx.strokeStyle = "rgba(120,200,255,.55)"; octx.lineWidth = 1.5 * dpr;
  octx.beginPath(); octx.moveTo(W * 0.3, H / 3); octx.lineTo(W * 0.7, H / 3); octx.stroke();
  octx.setLineDash([]);
  const f = S.face;
  if (!f || !f.found || performance.now() - S.lastFrameAt > 3000) return;
  const [x, y, w, h] = f.box;
  const good = !(f.framing && f.framing.length);
  octx.strokeStyle = good ? "rgba(51,196,107,.85)" : "rgba(120,200,255,.85)";
  octx.lineWidth = 1.5 * dpr;
  octx.strokeRect(x * W, y * H, w * W, h * H);
  octx.fillStyle = octx.strokeStyle;
  for (const [ex, ey] of f.eyes) { octx.beginPath(); octx.arc(ex * W, ey * H, 3 * dpr, 0, Math.PI * 2); octx.fill(); }
  octx.font = `600 ${11 * dpr}px ui-monospace, monospace`; octx.textAlign = "left";
  octx.fillText(`face ${f.face_luma}%`, x * W, y * H - 5 * dpr);
}

function drawLevel(W, H, dpr) {
  const h = S.header;
  if (!h || h.roll == null) return;
  const roll = h.roll, level = Math.abs(roll) < 0.5;
  const color = level ? "#33c46b" : "#f5a524";
  const len = Math.min(W, H) * 0.45;
  octx.save();
  octx.translate(W / 2, H / 2);
  // fixed reference ticks
  octx.strokeStyle = "rgba(255,255,255,.55)"; octx.lineWidth = 2 * dpr;
  octx.beginPath(); octx.moveTo(-len - 18 * dpr, 0); octx.lineTo(-len - 4 * dpr, 0); octx.moveTo(len + 4 * dpr, 0); octx.lineTo(len + 18 * dpr, 0); octx.stroke();
  // horizon: rotate opposite to the camera roll
  octx.rotate((-roll * Math.PI) / 180);
  octx.strokeStyle = color; octx.lineWidth = 2.5 * dpr;
  octx.beginPath(); octx.moveTo(-len, 0); octx.lineTo(-24 * dpr, 0); octx.moveTo(24 * dpr, 0); octx.lineTo(len, 0); octx.stroke();
  octx.restore();
  octx.fillStyle = color; octx.font = `600 ${12 * dpr}px ui-monospace, monospace`; octx.textAlign = "center";
  const pitch = h.pitch != null ? `  pitch ${h.pitch > 0 ? "+" : ""}${h.pitch.toFixed(1)}°` : "";
  octx.fillText(level ? `level${pitch}` : `tilt ${roll > 0 ? "+" : ""}${roll.toFixed(1)}°${pitch}`, W / 2, H / 2 + 22 * dpr);
}

let darkShown = null;
function updateDarkNote(img) {
  const d = img.data;
  let sum = 0, n = 0;
  for (let i = 0; i < d.length; i += 16) { sum += d[i] + d[i + 1] + d[i + 2]; n += 3; }
  const mean = sum / n;
  const note = $("#darkNote");
  let kind = null;
  if (mean < 10) kind = !isMovie() && V("exposure_preview") === 1 ? "preview" : "dark";
  if (kind === darkShown) return;
  darkShown = kind;
  note.hidden = !kind;
  note.innerHTML = "";
  if (kind === "preview") {
    note.append(el("span", { text: "Exposure preview is on — this is how dark the photo would be." }));
    const b = el("button", { class: "btn btn-sm", text: "Show brightened preview" });
    b.addEventListener("click", () => setValue(S.byKey.exposure_preview, 0));
    note.append(b);
  } else if (kind === "dark") {
    note.append(el("span", { text: "Very dark image — add light, open the aperture, use a slower shutter or raise ISO." }));
  }
}

function drawZebra(img, W, H) {
  const { data, width, height } = img, lvl = S.ui.zebraLevel;
  const mask = new ImageData(width, height);
  for (let y = 0, i = 0; y < height; y++) {
    for (let x = 0; x < width; x++, i += 4) {
      const l = 0.2126 * data[i] + 0.7152 * data[i + 1] + 0.0722 * data[i + 2];
      if (l >= lvl && ((x + y) >> 2) % 2 === 0) {
        mask.data[i] = 255; mask.data[i + 1] = 40; mask.data[i + 2] = 200; mask.data[i + 3] = 210;
      }
    }
  }
  paintMask(mask, W, H);
}

function drawPeaking(img, W, H) {
  const { data, width, height } = img;
  const lum = new Float32Array(width * height);
  for (let i = 0, j = 0; j < lum.length; i += 4, j++) lum[j] = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
  const mag = new Float32Array(width * height);
  let max = 1;
  for (let y = 1; y < height - 1; y++) {
    for (let x = 1; x < width - 1; x++) {
      const k = y * width + x;
      const gx = -lum[k - width - 1] - 2 * lum[k - 1] - lum[k + width - 1] + lum[k - width + 1] + 2 * lum[k + 1] + lum[k + width + 1];
      const gy = -lum[k - width - 1] - 2 * lum[k - width] - lum[k - width + 1] + lum[k + width - 1] + 2 * lum[k + width] + lum[k + width + 1];
      const m = gx * gx + gy * gy;
      mag[k] = m;
      if (m > max) max = m;
    }
  }
  // Highlight the strongest edges relative to the frame (adapts to dark scenes).
  const thr = Math.max(max * 0.18, 2500);
  const mask = new ImageData(width, height);
  for (let k = 0; k < mag.length; k++) {
    if (mag[k] >= thr) {
      const i = k * 4;
      mask.data[i] = 60; mask.data[i + 1] = 255; mask.data[i + 2] = 90; mask.data[i + 3] = 255;
    }
  }
  paintMask(mask, W, H);
}

const maskCanvas = document.createElement("canvas"), mctx = maskCanvas.getContext("2d");
function paintMask(mask, W, H) {
  maskCanvas.width = mask.width; maskCanvas.height = mask.height;
  mctx.putImageData(mask, 0, 0);
  octx.imageSmoothingEnabled = false;
  octx.drawImage(maskCanvas, 0, 0, W, H);
  octx.imageSmoothingEnabled = true;
}

function drawHistogram(img) {
  const { data } = img;
  const bins = [new Uint32Array(64), new Uint32Array(64), new Uint32Array(64), new Uint32Array(64)];
  for (let i = 0; i < data.length; i += 4) {
    const r = data[i], g = data[i + 1], b = data[i + 2];
    bins[0][r >> 2]++; bins[1][g >> 2]++; bins[2][b >> 2]++;
    bins[3][(0.2126 * r + 0.7152 * g + 0.0722 * b) >> 2]++;
  }
  const W = hist.width, H = hist.height;
  hctx.clearRect(0, 0, W, H);
  let max = 1;
  for (const b of bins) for (let i = 1; i < 63; i++) max = Math.max(max, b[i]);
  const colors = ["rgba(255,80,80,.55)", "rgba(80,220,110,.55)", "rgba(80,140,255,.55)", "rgba(235,235,235,.8)"];
  hctx.globalCompositeOperation = "lighter";
  bins.forEach((b, ci) => {
    hctx.fillStyle = colors[ci];
    hctx.beginPath(); hctx.moveTo(0, H);
    for (let i = 0; i < 64; i++) hctx.lineTo(i * W / 63, H - Math.min(1, b[i] / max) * (H - 6));
    hctx.lineTo(W, H); hctx.closePath();
    ci === 3 ? (hctx.globalCompositeOperation = "source-over", hctx.strokeStyle = colors[3], hctx.stroke()) : hctx.fill();
  });
  hctx.globalCompositeOperation = "source-over";
  // clipping warnings
  const total = data.length / 4;
  if (bins[3][63] / total > 0.01) { hctx.fillStyle = "#ff5a4f"; hctx.fillRect(W - 6, 0, 6, H); }
  if (bins[3][0] / total > 0.05) { hctx.fillStyle = "#4f7cff"; hctx.fillRect(0, 0, 6, H); }
}

function drawAfBox(W, H, dpr) {
  const h = S.header;
  if (!h || !h.af_w || !h.disp_w) return;
  const area = V("lv_af_area");
  if (area === 0 || area === 3) return; // face / subject tracking: the camera decides
  const sx = W / h.disp_w, sy = H / h.disp_h;
  const left = h.disp_cx - h.disp_w / 2, top = h.disp_cy - h.disp_h / 2;
  const bw = h.af_w * sx, bh = h.af_h * sy;
  const bx = (h.af_cx - left) * sx - bw / 2, by = (h.af_cy - top) * sy - bh / 2;
  const st = S.af.state, now = performance.now();
  let color = "rgba(255,255,255,.9)";
  if (st === "busy") color = "#f5a524";
  else if (st === "ok" && now < S.af.until) color = "#33c46b";
  else if (st === "fail" && now < S.af.until) color = "#ff5a4f";
  octx.strokeStyle = color;
  octx.lineWidth = 2 * dpr;
  const c = Math.min(bw, bh) * 0.28;
  octx.beginPath();
  for (const [x, y, dx, dy] of [[bx, by, 1, 1], [bx + bw, by, -1, 1], [bx, by + bh, 1, -1], [bx + bw, by + bh, -1, -1]]) {
    octx.moveTo(x + dx * c, y); octx.lineTo(x, y); octx.lineTo(x, y + dy * c);
  }
  octx.stroke();
}

overlay.addEventListener("click", async (e) => {
  if (!S.header) return;
  const r = overlay.getBoundingClientRect();
  const fx = (e.clientX - r.left) / r.width, fy = (e.clientY - r.top) / r.height;
  const onlyMove = e.shiftKey;
  if (!onlyMove) setAf("busy");
  try {
    const res = await send("focus_at", fx, fy, !onlyMove);
    if (!onlyMove) {
      if (res && res.focused === false) { setAf("fail"); toast("Couldn't lock focus there — try an area with more contrast or light", "error"); }
      else if (res && res.focused) setAf("ok");
      else setAf("idle");
    }
  } catch (err) {
    setAf("fail");
    toast(err.message, "error");
  }
  $("#clickHint").classList.add("fade");
});

function setAf(state) {
  S.af = { state, until: performance.now() + 1500 };
  drawOverlay();
  if (state !== "busy") setTimeout(drawOverlay, 1600);
}

/* ======================================================================
   Top bar + viewer state
   ====================================================================== */
function setServerDown(down) {
  if (down) {
    S.status.connected = false;
    showViewerMsg("The app server isn't running", "Start it again with <code>uv run nikon-remote</code>. This page reconnects automatically.", true);
    $("#connDot").className = "conn-dot bad";
    $("#connText").textContent = "App server offline";
  }
}

function showViewerMsg(title, bodyHtml, isError) {
  const m = $("#viewerMsg");
  m.hidden = false;
  m.classList.toggle("error", !!isError);
  $("#viewerMsgTitle").textContent = title;
  $("#viewerMsgBody").innerHTML = bodyHtml || "";
}

function renderViewerState() {
  const st = S.status;
  const m = $("#viewerMsg");
  if (!st.connected) {
    showViewerMsg("Camera not connected", `${escapeHtml(st.message || "")}<ul><li>Turn the camera on and wake it (half-press the shutter).</li><li>Use a USB <b>data</b> cable plugged straight into the PC.</li><li>Close Entangle or any other app that might be using the camera.</li></ul>`, true);
  } else if (st.lv_error) {
    showViewerMsg("Live view is blocked", escapeHtml(st.lv_error), true);
  } else if (!lastBitmap || performance.now() - S.lastFrameAt > 4000) {
    showViewerMsg("Starting live view…", st.lv ? "" : "The mirror flips up and the preview appears in a second.", false);
  } else {
    m.hidden = true;
  }
  $("#fpsPill").textContent = st.lv ? `${st.fps || 0} fps` : "LV off";
  const zv = V("lv_zoom");
  const zoomed = !!zv;
  const zl = zoomed ? fmtValue(S.byKey.lv_zoom, zv) : "";
  $("#zoomPill").hidden = !zoomed;
  $("#zoomPill").textContent = `Zoom ${zl}`;
  $("#zoomLabel").textContent = zoomed ? zl : "Zoom";
  $("#zoomBtn").classList.toggle("on", zoomed);
}

function renderTopbar() {
  const st = S.status;
  $("#connDot").className = "conn-dot " + (st.connected ? "ok" : "bad");
  $("#camName").textContent = st.model ? `Nikon ${st.model}` : "Nikon Remote";
  $("#connText").textContent = st.connected ? `Connected · fw ${st.firmware || ""}` : (st.message || "Not connected");

  const mode = S.byKey.mode;
  $("#modeVal").textContent = fmtValue(mode, V("mode"));

  const sel = V("lv_selector");
  $$("#lvSelector button").forEach((b) => b.classList.toggle("on", Number(b.dataset.v) === sel));

  const fs = S.byKey.frame_size;
  $("#formatChip").hidden = !isMovie();
  $("#formatVal").textContent = fmtValue(fs, V("frame_size"));

  const bat = st.battery;
  $("#batteryVal").textContent = bat == null ? "–" : `${bat}%`;
  $("#batteryChip").className = "chip" + (bat != null && bat <= 10 ? " bad" : bat != null && bat <= 25 ? " warn" : "");
  $("#batteryChip").title = st.ac_power ? "Running on AC power" : "Battery";

  const noCard = (st.movie_prohibit || []).some((r) => /card/i.test(r));
  $("#cardVal").textContent = noCard ? "Card issue" : st.remaining_shots != null ? `${st.remaining_shots} shots` : "–";
  $("#cardChip").className = "chip" + (noCard ? " bad" : "");
  $("#cardChip").title = st.last_clip ? `Last clip: ${st.last_clip.name} (${fmtBytes(st.last_clip.size)})` : "Card";


  const onPc = S.ui.recordOn === "pc";
  $("#recBtn").hidden = onPc && !st.recording;
  $("#micMeter").hidden = !onPc || !!st.recording;
  $("#cardChip").hidden = onPc;
  const bm = S.session.battery_minutes;
  if (bm != null && !st.ac_power) $("#batteryVal").textContent = `${bat}% · ~${fmtDuration(bm)}`;
  const lvLeft = st.lv && S.header ? S.header.lv_remaining_s : null;
  $("#lvTimerChip").hidden = lvLeft == null;
  if (lvLeft != null) {
    $("#lvTimerVal").textContent = `LV ${fmtClock(lvLeft)}`;
    $("#lvTimerChip").className = "chip" + (lvLeft < 60 ? " bad" : lvLeft < 180 ? " warn" : "");
  }
  $("#diskChip").hidden = !onPc || S.session.disk_minutes == null;
  if (S.session.disk_minutes != null) {
    $("#diskVal").textContent = `${S.session.disk_free_gb} GB · ~${fmtDuration(S.session.disk_minutes)}`;
    $("#diskChip").className = "chip" + (S.session.disk_minutes < 30 ? " bad" : S.session.disk_minutes < 90 ? " warn" : "");
  }
  const rec = !!st.recording;
  $("#recBtn").classList.toggle("on", rec);
  const bodyOnly = !rec && bodyOnlyRecording() && !recBlockers().length;
  $("#recLabel").textContent = rec ? fmtClock(st.rec_elapsed || 0) : bodyOnly ? "ON CAMERA" : "REC";
  $("#recBtn").classList.toggle("body-only", bodyOnly);
  $("#recBadge").hidden = !rec;
  $("#recTime").textContent = fmtClock(st.rec_elapsed || 0);
  const left = S.header && S.header.clip_remaining_ms;
  $("#recLeft").textContent = rec && left ? ` · ${fmtClock(Math.floor(left / 1000))} left` : "";
  viewer.classList.toggle("recording", rec);
  $("#recBtn").disabled = !st.connected || (!rec && !isMovie());
  $("#recBtn").title = !isMovie() ? "Switch live view to Movie to record"
    : rec ? "Stop recording (R)"
    : bodyOnly ? "Press the red ● record button on the camera to start — the D7500 doesn't allow starting from a computer. The timer appears here."
    : "Start recording (R)";

  renderMeter();
}

const METER_STEPS_PER_EV = 6;
function renderMeter() {
  const v = S.status.meter;
  const meter = $("#meter");
  const off = v == null || !S.status.lv;
  meter.classList.toggle("off", off);
  if (off) { $("#meterVal").textContent = "–"; return; }
  const ev = v / METER_STEPS_PER_EV;
  const clamped = Math.max(-3, Math.min(3, ev));
  $("#meterNeedle").style.left = `${((clamped + 3) / 6) * 100}%`;
  $("#meterVal").textContent = Math.abs(ev) > 3 ? (ev > 0 ? "over +3 EV" : "under −3 EV") : `${ev >= 0 ? "+" : "−"}${Math.abs(ev).toFixed(1)} EV`;
}

/* ======================================================================
   Dials (quick exposure controls)
   ====================================================================== */
const DIALS = [
  { name: "Shutter", key: () => (isMovie() ? "movie_shutter" : "shutter") },
  { name: "Aperture", key: () => (isMovie() ? "movie_aperture" : "aperture") },
  { name: "ISO", key: () => (isMovie() ? "movie_iso" : "iso") },
  { name: "EV", key: () => (isMovie() ? "movie_ev" : "ev") },
  { name: "WB", key: () => (isMovie() ? "movie_wb" : "wb") },
  { name: "Kelvin", key: () => (isMovie() ? "movie_kelvin" : "kelvin"), when: () => V(isMovie() ? "movie_wb" : "wb") === 0x8012 },
];

function renderDials() {
  const box = $("#dials");
  const visible = DIALS.filter((d) => !d.when || d.when());
  if (box.childElementCount !== visible.length || box.dataset.sig !== visible.map((d) => d.name).join()) {
    box.innerHTML = "";
    box.dataset.sig = visible.map((d) => d.name).join();
    visible.forEach((d, i) => box.append(buildDial(d, i)));
  }
  visible.forEach((d, i) => updateDial(box.children[i], d, i));
}

function buildDial(d, i) {
  const dial = el("div", { class: "dial", tabindex: "0", "data-dial": d.name });
  const info = el("button", { class: "dial-info", title: `What is ${d.name}?`, "aria-label": `What is ${d.name}?` }, icon("i-info"));
  info.addEventListener("click", (e) => { e.stopPropagation(); showHelpPop(info, S.byKey[d.key()]); });
  const label = el("div", { class: "dial-label" }, el("span", { class: "dial-name" }, d.name, info), el("span", { class: "dial-lock" }));
  const prev = el("button", { class: "dial-step", title: "Previous value (←)" }, icon("i-chev-l"));
  const val = el("button", { class: "dial-value", title: "Click for all values · scroll to change" });
  const next = el("button", { class: "dial-step", title: "Next value (→)" }, icon("i-chev-r"));
  dial.append(label, el("div", { class: "dial-body" }, prev, val, next));
  prev.addEventListener("click", () => stepDial(d, -1));
  next.addEventListener("click", () => stepDial(d, +1));
  val.addEventListener("click", () => openValuePicker(val, S.byKey[d.key()]));
  dial.addEventListener("focus", () => { S.selectedDial = i; renderDials(); });
  let acc = 0, lastWheel = 0;
  dial.addEventListener("wheel", (e) => {
    e.preventDefault();
    acc += e.deltaY;
    const now = performance.now();
    if (Math.abs(acc) >= 40 || now - lastWheel > 180) {
      stepDial(d, acc < 0 || (acc === 0 && e.deltaY < 0) ? +1 : -1);
      acc = 0; lastWheel = now;
    }
  }, { passive: false });
  return dial;
}

function updateDial(node, d, i) {
  const s = S.byKey[d.key()];
  const p = s && S.props[s.code];
  node.classList.toggle("selected", S.selectedDial === i);
  const pending = s && S.pending[s.code];
  const value = pending !== undefined ? pending : p && p.v;
  const valBtn = $(".dial-value", node);
  valBtn.textContent = p ? fmtValue(s, value) : "–";
  valBtn.style.opacity = pending !== undefined ? 0.55 : 1;
  const locked = !p || !p.w;
  node.classList.toggle("locked", locked);
  const lock = $(".dial-lock", node);
  lock.innerHTML = "";
  if (locked && p) { lock.append(icon("i-lock")); }
  node.title = locked ? lockReason(s) : `${d.name}: ${s ? s.help || "" : ""}`;
  const ch = choicesOf(p), idx = ch.indexOf(value);
  $$(".dial-step", node)[0].disabled = locked || idx <= 0;
  $$(".dial-step", node)[1].disabled = locked || idx < 0 || idx >= ch.length - 1;
  valBtn.disabled = locked;
}

function stepDial(d, dir) {
  const s = S.byKey[d.key()];
  const p = s && S.props[s.code];
  if (!p || !p.w) { if (s) toast(lockReason(s), "error"); return; }
  const ch = choicesOf(p);
  const cur = S.pending[s.code] !== undefined ? S.pending[s.code] : p.v;
  const idx = ch.indexOf(cur);
  const nidx = Math.max(0, Math.min(ch.length - 1, (idx < 0 ? 0 : idx) + dir));
  if (ch[nidx] === undefined || ch[nidx] === cur) return;
  setValue(s, ch[nidx]);
}

async function setValue(s, value) {
  S.pending[s.code] = value;
  renderAll();
  try {
    await send("set", s.code, value);
  } catch (e) {
    toast(`${s.label}: ${e.message}`, "error");
  } finally {
    delete S.pending[s.code];
    renderAll();
  }
}

function lockReason(s) {
  if (!s) return "Not available";
  const mode = V("mode");
  const exposureKeys = ["movie_shutter", "movie_aperture", "shutter", "aperture"];
  if (!S.props[s.code]) return "This camera doesn't report this setting right now";
  if (exposureKeys.includes(s.key) && mode !== 1 && !((mode === 3 && s.key.includes("aperture")) || (mode === 4 && s.key.includes("shutter"))))
    return `Controlled by the camera in ${fmtValue(S.byKey.mode, mode)} mode — switch to M (click the Mode chip at the top).`;
  if (s.key.endsWith("iso") && (V(isMovie() ? "movie_auto_iso" : "auto_iso") === 1)) return "Auto ISO is on — the camera sets ISO itself.";
  if (s.pc_mode && !S.status.lv) return "Can be changed from here while live view is running.";
  if (UNSAFE_CODES.has(s.code)) return "Changing this makes the D7500 stop responding, so the app doesn't allow it.";
  if (s.scope === "movie" && !isMovie()) return "Movie setting — switch live view to Movie to change it.";
  if (s.scope === "photo" && isMovie()) return "Photo setting — switch live view to Photo to change it.";
  if (S.status.recording) return "Can't be changed while recording.";
  return "The camera doesn't allow changing this right now.";
}

/* ======================================================================
   Popover value picker
   ====================================================================== */
const pop = $("#popover");
function openValuePicker(anchor, s) {
  const p = s && S.props[s.code];
  if (!p || !p.w) { if (s) toast(lockReason(s), "error"); return; }
  const ch = choicesOf(p);
  if (!ch.length) return;
  pop.innerHTML = "";
  const grid = el("div", { class: "pop-grid" });
  for (const v of ch) {
    const b = el("button", { class: v === p.v ? "on" : "", text: fmtValue(s, v) });
    b.addEventListener("click", () => { closePop(); setValue(s, v); });
    grid.append(b);
  }
  pop.append(grid);
  pop.hidden = false;
  const r = anchor.getBoundingClientRect();
  const pw = pop.offsetWidth, ph = pop.offsetHeight;
  let left = Math.min(window.innerWidth - pw - 8, Math.max(8, r.left + r.width / 2 - pw / 2));
  let top = r.top - ph - 8;
  if (top < 8) top = r.bottom + 8;
  pop.style.left = left + "px"; pop.style.top = top + "px";
  const on = $(".on", pop);
  if (on) on.scrollIntoView({ block: "center" });
}
function closePop() { pop.hidden = true; }
function showHelpPop(anchor, s) {
  if (!s) return;
  pop.innerHTML = "";
  pop.append(el("div", { class: "help-pop" }, el("strong", { text: s.label }), el("p", { text: s.help || "" })));
  pop.hidden = false;
  const r = anchor.getBoundingClientRect();
  const pw = pop.offsetWidth, ph = pop.offsetHeight;
  pop.style.left = Math.min(window.innerWidth - pw - 8, Math.max(8, r.left - 20)) + "px";
  pop.style.top = (r.top - ph - 8 < 8 ? r.bottom + 8 : r.top - ph - 8) + "px";
}
document.addEventListener("mousedown", (e) => { if (!pop.hidden && !pop.contains(e.target)) closePop(); });

/* ======================================================================
   Focus controls
   ====================================================================== */
$("#afBtn").addEventListener("click", doAutofocus);
async function doAutofocus() {
  setAf("busy");
  try {
    const r = await send("autofocus");
    if (r && r.focused) setAf("ok");
    else { setAf("fail"); toast("Couldn't lock focus — try more light, more contrast, or move the focus point", "error"); }
  } catch (e) { setAf("fail"); toast(e.message, "error"); }
}
// The 18-140 travels ~6000 drive steps end to end; these are ~0.3%, 1.5% and 8% of that.
const MF_STEPS = { fine: 20, medium: 100, big: 500 };
$$(".mf button").forEach((b) => b.addEventListener("click", () => manualFocus(Math.sign(Number(b.dataset.mf)) * MF_STEPS[b.dataset.size])));
async function manualFocus(steps) {
  try {
    const r = await send("manual_focus", steps);
    if (r && r.limit) toast(steps < 0 ? "Focus is at the near end of its range" : "Focus is at the far end (infinity)", "info");
  } catch (e) { toast(e.message, "error"); }
}

function renderFocusControls() {
  const s = S.byKey.lv_af_mode, p = s && S.props[s.code];
  const seg = $("#afModeSeg");
  const vals = p ? choicesOf(p).filter((v) => S.byKey.lv_af_mode.labels[String(v)]) : [];
  if (seg.dataset.sig !== vals.join()) {
    seg.innerHTML = "";
    seg.dataset.sig = vals.join();
    for (const v of vals) {
      const b = el("button", { text: fmtValue(s, v), "data-v": v });
      b.addEventListener("click", () => setValue(s, v));
      seg.append(b);
    }
  }
  $$("button", seg).forEach((b) => { b.classList.toggle("on", Number(b.dataset.v) === (p && p.v)); b.disabled = !p || !p.w; });
  seg.title = p && !p.w ? lockReason(s) : "Live view focus mode: AF-S focuses when asked, AF-F keeps focusing, MF is manual";

  const a = S.byKey.lv_af_area, ap = a && S.props[a.code];
  const sel = $("#afAreaSel");
  const avals = ap ? choicesOf(ap) : [];
  if (sel.dataset.sig !== avals.join()) {
    sel.innerHTML = "";
    sel.dataset.sig = avals.join();
    for (const v of avals) sel.append(el("option", { value: v, text: fmtValue(a, v) }));
  }
  if (ap) sel.value = ap.v;
  sel.disabled = !ap || !ap.w;
  const mfMode = p && (p.v === 3 || p.v === 4);
  $("#afBtn").disabled = !S.status.lv || mfMode;
  $("#afBtn").title = mfMode ? "Focus mode is MF — switch to AF-S or AF-F to autofocus" : "Autofocus at the focus point (F)";
  const area = ap && ap.v;
  $("#clickHint").textContent = area === 0 || area === 3
    ? "Click to focus (the camera picks faces/subjects in this AF-area mode)"
    : "Click to focus · Shift+click to move the point only";
}
$("#afAreaSel").addEventListener("change", (e) => setValue(S.byKey.lv_af_area, Number(e.target.value)));

$("#zoomBtn").addEventListener("click", cycleZoom);
function cycleZoom() {
  const s = S.byKey.lv_zoom, p = s && S.props[s.code];
  if (!p || !p.w) { toast(s ? lockReason(s) : "Zoom not available", "error"); return; }
  const ch = choicesOf(p);
  const order = [0, 4, 6, 7].filter((v) => ch.includes(v));
  const pos = order.indexOf(p.v);
  setValue(s, order[(pos + 1) % order.length]);
}

/* ======================================================================
   Overlays toggles
   ====================================================================== */
function renderOverlayToggles() {
  $$("#overlayToggles button").forEach((b) => b.classList.toggle("on", !!S.ui.overlays[b.dataset.ov]));
  hist.hidden = !S.ui.overlays.hist;
}
$$("#overlayToggles button").forEach((b) => b.addEventListener("click", () => toggleOverlay(b.dataset.ov)));
function toggleOverlay(k) {
  S.ui.overlays[k] = !S.ui.overlays[k];
  savePrefs(); renderOverlayToggles(); drawOverlay();
}

/* ======================================================================
   Pre-flight checklist
   ====================================================================== */
function computeChecks() {
  const st = S.status, out = [];
  const add = (level, title, detail, fix) => out.push({ level, title, detail, fix });
  if (!st.connected) { add("bad", "Camera not connected", st.message || ""); return out; }

  if (st.lv_error) add("bad", "Live view blocked", st.lv_error);

  if (S.ui.activePreset && presets[S.ui.activePreset]) {
    const diffs = presetDiff(S.ui.activePreset);
    if (diffs && diffs.length) add("warn", `Differs from “${S.ui.activePreset}”`, diffs.join(" · "), { label: "Re-apply", run: () => applyPreset(S.ui.activePreset) });
    else if (diffs) add("ok", `Matches “${S.ui.activePreset}”`);
  }

  const movie = isMovie();
  if (!movie) add("warn", "Live view is in Photo mode", "Recording needs Movie. Flip the camera's Lv switch to the movie icon.", null);
  else add("ok", "Live view in Movie mode");

  const onPc = S.ui.recordOn === "pc";
  if (onPc) {
    const a = S.audio || {};
    if (a.error) add("bad", "No audio from the mixer", a.error);
    else if (a.clipping) add("bad", "Mic is clipping", "Turn GAIN down on your mic channel.");
    else if (!S.voiceReport) add("warn", "Voice not checked yet", "Run the voice check in the Voice & mic panel.", { label: "Check now", run: () => { expandCard("audioCard"); $("#voiceCheckBtn").click(); } });
    else if (S.voiceReport.recommendations.some((x) => x.level === "bad")) {
      add("bad", "Voice check found a problem", S.voiceReport.recommendations.find((x) => x.level === "bad").text, { label: "Show", run: () => expandCard("audioCard") });
    } else {
      const todo = S.voiceReport.recommendations.filter((x) => x.level !== "ok").length;
      if (todo) add("warn", `Mixer: ${todo} adjustment${todo > 1 ? "s" : ""} suggested`, "See the Voice & mic panel, then check again.", { label: "Show", run: () => expandCard("audioCard") });
      else add("ok", "Voice checked — mixer set");
    }
    const fi = faceItems().filter((i) => i.level !== "ok");
    if (st.lv && S.face) {
      if (fi.length) add("warn", `Face check: ${fi.map((i) => i.title.toLowerCase()).join(", ")}`, null, { label: "Show", run: () => expandCard("faceCard") });
      else add("ok", "Face exposure, focus and framing good");
    }
    const lvLeft = st.lv && S.header ? S.header.lv_remaining_s : null;
    if (lvLeft != null && lvLeft < 180) add("warn", `Live view turns off in ${fmtClock(lvLeft)}`, "The HDMI feed stops with it. Reset between takes.", { label: "Reset timer", run: () => $("#lvTimerChip").click() });
    if (S.session.disk_minutes != null && S.session.disk_minutes < 30) add("bad", `PC disk: about ${S.session.disk_minutes} min of recording left`, `Free up space in ${S.session.record_dir}.`);
  }
  if (S.session.battery_minutes != null && S.session.battery_minutes < 20 && !st.ac_power) add("warn", `Camera battery: about ${S.session.battery_minutes} min left`, "Swap the battery before a long take, or use the mains adapter.");

  if (movie && !st.recording && !onPc) {
    if (recBlockers().length) add("bad", "Recording is blocked", recBlockers().join(" · "));
    else if (bodyOnlyRecording()) add("ok", "Ready — start with the camera's ● button", "The D7500 doesn't let a computer start a take. The app shows the timer and keeps the preview running.");
    else add("ok", "Ready to record");
  } else if (st.recording) add("ok", "Recording");

  const mode = V("mode");
  if (mode !== undefined) {
    if (mode === 1) add("ok", "Exposure mode M");
    else add("warn", `Exposure mode is ${fmtValue(S.byKey.mode, mode)}`, "Use M for consistent video exposure.", { label: "Set M", run: () => setValue(S.byKey.mode, 1) });
  }

  const autoIsoKey = movie ? "movie_auto_iso" : "auto_iso";
  if (V(autoIsoKey) === 1) add("warn", "Auto ISO is on", "ISO will drift during the shot.", P(autoIsoKey) && P(autoIsoKey).w ? { label: "Turn off", run: () => setValue(S.byKey[autoIsoKey], 0) } : null);
  else if (V(autoIsoKey) === 0) add("ok", "Auto ISO off");

  if (movie) {
    const fsLabel = fmtValue(S.byKey.frame_size, V("frame_size"));
    const m = /(\d+)p/.exec(fsLabel);
    const secs = shutterSeconds(V("movie_shutter") ?? 0);
    if (m && secs) {
      const fps = Number(m[1]);
      const ideal = 1 / (2 * fps);
      const ratio = secs / ideal;
      const p = P("movie_shutter");
      const best = p && p.vals ? p.vals.filter((v) => shutterSeconds(v)).reduce((a, b) => Math.abs(Math.log(shutterSeconds(b) / ideal)) < Math.abs(Math.log(shutterSeconds(a) / ideal)) ? b : a) : null;
      const fix = best && p.w && best !== V("movie_shutter") ? { label: `Use ${fmtShutter(best)}`, run: () => setValue(S.byKey.movie_shutter, best) } : null;
      if (ratio > 1.3) add("warn", `Shutter ${fmtShutter(V("movie_shutter"))} is slow for ${fps}p`, `Expect extra motion blur. The 180° rule suggests about 1/${2 * fps}.`, fix);
      else if (ratio < 0.45) add("warn", `Shutter ${fmtShutter(V("movie_shutter"))} is fast for ${fps}p`, `Motion may look choppy. The 180° rule suggests about 1/${2 * fps}.`, fix);
      else add("ok", `Shutter ${fmtShutter(V("movie_shutter"))} suits ${fps}p`);
    }
  }

  const wbKey = movie ? "movie_wb" : "wb";
  if (V(wbKey) === 2) add("warn", "White balance is Auto", "Color can shift during a shot. Pick a preset or a Kelvin value.", { label: "Use 5600 K", run: async () => { await setValue(S.byKey[wbKey], 0x8012); await setValue(S.byKey[movie ? "movie_kelvin" : "kelvin"], 5600); } });
  else if (V(wbKey) !== undefined) add("ok", `White balance ${fmtValue(S.byKey[wbKey], V(wbKey))}`);

  const faceJudges = S.ui.recordOn === "pc" && S.face && S.face.found;
  if (st.meter != null && st.lv && mode === 1 && !faceJudges) {
    const ev = st.meter / METER_STEPS_PER_EV;
    if (Math.abs(ev) > 1) add("warn", `Meter reads ${ev > 0 ? "+" : "−"}${Math.abs(ev).toFixed(1)} EV`, ev > 0 ? "Likely overexposed — faster shutter, smaller aperture or lower ISO." : "Likely underexposed — more light, wider aperture or higher ISO.");
    else add("ok", "Exposure within ±1 EV of the meter");
  }

  if (movie && V("mic") === 4) add("warn", "Microphone is off", "The clip will have no audio.", P("mic") && P("mic").w ? { label: "Turn on (Auto)", run: () => setValue(S.byKey.mic, 0) } : null);

  if (st.battery != null) {
    if (st.battery <= 10 && !st.ac_power) add("bad", `Battery ${st.battery}%`, "Charge or swap the battery before recording.");
    else if (st.battery <= 25 && !st.ac_power) add("warn", `Battery ${st.battery}%`, "Recording could stop soon.");
    else add("ok", st.ac_power ? "On AC power" : `Battery ${st.battery}%`);
  }

  const clock = V("clock");
  if (typeof clock === "string" && /^\d{8}T\d{6}/.test(clock)) {
    const d = new Date(+clock.slice(0, 4), +clock.slice(4, 6) - 1, +clock.slice(6, 8), +clock.slice(9, 11), +clock.slice(11, 13), +clock.slice(13, 15));
    const diff = Math.abs(d - new Date()) / 60000;
    if (diff > 3) add("warn", "Camera clock is wrong", `It says ${d.toLocaleString()}. File dates will be off.`, P("clock") && P("clock").w ? { label: "Sync to PC", run: () => run("sync_clock").then(() => toast("Camera clock synced", "ok")) } : null);
  }
  return out;
}

function renderChecks() {
  const checks = computeChecks();
  const list = $("#checkList");
  list.innerHTML = "";
  const order = { bad: 0, warn: 1, ok: 2 };
  checks.sort((a, b) => order[a.level] - order[b.level]);
  for (const c of checks) {
    const li = el("li", { class: c.level },
      icon(c.level === "ok" ? "i-check" : c.level === "bad" ? "i-x" : "i-warn"),
      el("div", { class: "check-text" }, el("div", { class: "check-title", text: c.title }), c.detail ? el("div", { class: "check-detail", text: c.detail }) : null));
    if (c.fix) {
      const b = el("button", { class: "btn btn-sm", text: c.fix.label });
      b.addEventListener("click", () => c.fix.run());
      li.append(b);
    }
    list.append(li);
  }
  const bad = checks.filter((c) => c.level === "bad").length, warn = checks.filter((c) => c.level === "warn").length;
  const sum = $("#checksSummary");
  sum.textContent = bad ? `${bad} problem${bad > 1 ? "s" : ""}` : warn ? `${warn} to review` : "All good";
  sum.className = "checks-summary " + (bad || warn ? "warn" : "ok");
}

/* ======================================================================
   Settings tabs
   ====================================================================== */
function buildTabs() {
  const tabs = $("#tabs");
  tabs.innerHTML = "";
  const all = [...S.catalog.sections, { key: "all", label: "All settings" }];
  if (!all.some((t) => t.key === S.ui.tab)) S.ui.tab = "exposure";
  for (const t of all) {
    const b = el("button", { role: "tab", "data-tab": t.key, text: t.label });
    b.addEventListener("click", () => { S.ui.tab = t.key; savePrefs(); renderTabs(true); });
    tabs.append(b);
  }
}

let allFilter = "";
function renderTabs(force = false) {
  if (!S.catalog) return;
  $$("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === S.ui.tab));
  const body = $("#tabBody");
  const note = $("#scopeNote");
  const active = document.activeElement;
  if (!force && body.contains(active) && (active.tagName === "INPUT" || active.tagName === "SELECT")) return; // don't clobber typing
  if (S.ui.tab === "all") { note.innerHTML = ""; renderAllTab(body); return; }

  note.innerHTML = "";
  note.append(
    el("span", { text: isMovie() ? "Showing movie settings" : "Showing photo settings" }),
    el("label", {}, Object.assign(el("input", { type: "checkbox" }), { checked: S.ui.otherScope, onchange: (e) => { S.ui.otherScope = e.target.checked; savePrefs(); renderTabs(true); } }), isMovie() ? "Also show photo settings" : "Also show movie settings"),
  );
  body.innerHTML = "";
  const list = S.catalog.settings.filter((s) => s.section === S.ui.tab);
  const primary = list.filter(scopeMatches);
  const other = list.filter((s) => !scopeMatches(s));
  for (const s of primary) body.append(settingRow(s));
  if (S.ui.otherScope && other.length) {
    body.append(el("div", { class: "group-title", text: isMovie() ? "Photo settings" : "Movie settings" }));
    for (const s of other) body.append(settingRow(s));
  }
  if (S.ui.tab === "setup") {
    const cameraRows = [...body.children];
    body.innerHTML = "";
    body.append(el("div", { class: "group-title", text: "Recording" }));
    const recRow = el("div", { class: "row" }, el("div", { class: "row-label" }, el("span", { text: "I record on" }),
      el("button", { class: "tip", title: "PC: HDMI capture card + recording software (the mic meter replaces the REC button and card checks are hidden). Camera: the camera's own card." }, icon("i-info"))), el("div", { class: "row-ctl" }));
    const recSeg = el("div", { class: "seg" });
    for (const [label, v] of [["PC (capture card)", "pc"], ["Camera card", "camera"]]) {
      const b = el("button", { class: S.ui.recordOn === v ? "on" : "", text: label });
      b.addEventListener("click", () => { S.ui.recordOn = v; savePrefs(); renderAll(); });
      recSeg.append(b);
    }
    $(".row-ctl", recRow).append(recSeg);
    body.append(recRow);
    if (S.assist) {
      const cfgRow = (label, key, help, type = "text", width) => {
        const inp = el("input", { class: "text-ctl", type, value: S.assist[key], style: width ? `width:${width}` : null });
        inp.addEventListener("change", () => run("assist_config", key, type === "number" ? Number(inp.value) : inp.value)
          .then((r) => { Object.assign(S.assist, r); toast(`${label} saved`, "ok"); }).catch(() => {}));
        return el("div", { class: "row" }, el("div", { class: "row-label" }, el("span", { text: label }), el("button", { class: "tip", title: help }, icon("i-info"))), el("div", { class: "row-ctl" }, inp));
      };
      body.append(cfgRow("Recordings folder", "record_dir", "Where your recording software saves files — used for the disk-space warning."));
      body.append(cfgRow("Recording bitrate (Mbps)", "record_mbps", "Your recording software's video bitrate, for the minutes-left estimate. OBS 1080p30 is typically 20–50.", "number", "90px"));
      body.append(el("div", { class: "group-title", text: "Face check" }));
      body.append(cfgRow("Face brightness target (%)", "face_target", "The face brightness “Expose for my face” aims for. Easiest: when your face looks right, press “Remember this brightness”.", "number", "90px"));
      body.append(cfgRow("Highest ISO it may use", "max_iso", "“Expose for my face” won't go above this (noise). D7500: 3200–6400 is fine for YouTube.", "number", "90px"));
    }
    body.append(el("div", { class: "group-title", text: "Camera" }));
    cameraRows.forEach((r) => body.append(r));
    const pc = el("div", { class: "row" },
      el("div", { class: "row-label" }, el("span", { text: "PC control mode" }),
        el("span", { class: "tip", title: "Advanced. Lets the app change dial-bound settings (exposure mode, Lv switch) even when live view is off. The camera may refuse to record while it's on." }, icon("i-info"))),
      el("div", { class: "row-ctl" }));
    const seg = el("div", { class: "seg" });
    for (const [label, on] of [["Off", false], ["On", true]]) {
      const b = el("button", { class: !!S.status.pc_mode === on ? "on" : "", text: label });
      b.addEventListener("click", () => run("pc_mode", on).then(() => toast(on ? "PC control on" : "PC control off", "ok")).catch(() => {}));
      seg.append(b);
    }
    $(".row-ctl", pc).append(seg);
    body.append(pc);
    const b = el("button", { class: "btn", style: "margin:10px 6px" }, icon("i-refresh"), "Re-read all settings from the camera");
    b.addEventListener("click", () => run("refresh").then(() => toast("Settings refreshed", "ok")));
    body.append(b);
  }
  if (S.ui.tab === "exposure") {
    body.append(el("div", { class: "adv-note", style: "padding:10px 6px", text: "Shutter, aperture, ISO, EV, white balance and focus are the controls under the preview." }));
  }
}

function settingRow(s) {
  const p = S.props[s.code];
  const row = el("div", { class: "row", "data-code": s.code });
  const label = el("div", { class: "row-label" }, el("span", { text: s.label }));
  if (s.help) {
    const tip = el("button", { class: "tip", title: s.help, "aria-label": `About ${s.label}` }, icon("i-info"));
    tip.addEventListener("click", () => showHelpPop(tip, s));
    label.append(tip);
  }
  const ctl = el("div", { class: "row-ctl" });
  row.append(label, ctl);
  if (!p) { ctl.append(el("span", { class: "ro-value", text: "not available" })); row.classList.add("locked"); return row; }
  if (!p.w || UNSAFE_CODES.has(s.code)) {
    row.classList.add("locked");
    ctl.append(el("span", { class: "ro-value", title: lockReason(s) }, fmtValue(s, p.v), icon("i-lock")));
    return row;
  }
  ctl.append(controlFor(s, p));
  return row;
}

function controlFor(s, p) {
  const pending = S.pending[s.code];
  const cur = pending !== undefined ? pending : p.v;
  if (s.fmt === "text" || p.dt === 0xffff) {
    const inp = el("input", { class: "text-ctl", value: String(cur ?? "").trim(), placeholder: "(empty)" });
    const commit = () => { if (inp.value !== String(p.v ?? "").trim()) setValue(s, inp.value); };
    inp.addEventListener("keydown", (e) => { if (e.key === "Enter") inp.blur(); });
    inp.addEventListener("blur", commit);
    return inp;
  }
  const ch = choicesOf(p);
  if (p.form === "range" && (s.fmt === "kelvin" || s.fmt === "raw") && (p.max - p.min) / (p.step || 1) > 12) {
    const wrap = el("div", { class: "range-ctl" });
    const r = el("input", { type: "range", min: p.min, max: p.max, step: p.step || 1, value: cur });
    const n = el("input", { type: "number", min: p.min, max: p.max, step: p.step || 1, value: cur });
    r.addEventListener("input", () => (n.value = r.value));
    r.addEventListener("change", () => setValue(s, Number(r.value)));
    n.addEventListener("change", () => setValue(s, Number(n.value)));
    wrap.append(r, n);
    return wrap;
  }
  if (ch.length && ch.length <= 4 && ch.every((v) => fmtValue(s, v).length <= 16)) {
    const seg = el("div", { class: "seg" });
    for (const v of ch) {
      const b = el("button", { class: v === cur ? "on" : "", text: fmtValue(s, v) });
      b.addEventListener("click", () => setValue(s, v));
      seg.append(b);
    }
    return seg;
  }
  const sel = el("select", { class: "select" });
  for (const v of ch) sel.append(el("option", { value: v, text: fmtValue(s, v) }));
  if (!ch.includes(cur)) sel.append(el("option", { value: cur, text: fmtValue(s, cur) }));
  sel.value = cur;
  sel.addEventListener("change", () => setValue(s, Number(sel.value)));
  return sel;
}

function renderAllTab(body) {
  const keepFocus = document.activeElement && document.activeElement.id === "allSearch";
  body.innerHTML = "";
  const search = el("div", { class: "search" }, icon("i-search"));
  const inp = el("input", { id: "allSearch", placeholder: "Search all camera properties…", value: allFilter });
  inp.addEventListener("input", () => { allFilter = inp.value; renderAllTab(body); });
  search.append(inp);
  body.append(search, el("div", { class: "adv-note", text: "Every property the camera exposes, with raw values. Anything with a friendly control lives in the other tabs." }));
  const q = allFilter.trim().toLowerCase();
  const codes = Object.keys(S.props).map(Number).sort((a, b) => a - b);
  let shown = 0;
  for (const code of codes) {
    const name = S.names[code] || `Property 0x${code.toString(16)}`;
    const known = S.byCode[code];
    const label = known ? known.label : name;
    const hex = "0x" + code.toString(16).padStart(4, "0");
    if (q && !(`${label} ${name} ${hex}`.toLowerCase().includes(q))) continue;
    const p = S.props[code];
    const s = known || { code, key: `raw_${code}`, label, fmt: p.dt === 0xffff ? "text" : "raw", scope: "both" };
    const row = settingRow(s);
    $(".row-label", row).append(el("span", { class: "code", text: hex }));
    body.append(row);
    shown++;
  }
  if (!shown) body.append(el("div", { class: "adv-note", text: "No properties match." }));
  if (keepFocus) { const i = $("#allSearch"); i.focus(); i.setSelectionRange(i.value.length, i.value.length); }
}

function markChanged(codes) {
  requestAnimationFrame(() => {
    for (const c of codes) {
      const r = $(`#tabBody .row[data-code="${c}"]`);
      if (r) { r.classList.remove("changed"); void r.offsetWidth; r.classList.add("changed"); }
    }
  });
}

/* ======================================================================
   Top bar controls
   ====================================================================== */

$$("#lvSelector button").forEach((b) => b.addEventListener("click", () => {
  const v = Number(b.dataset.v);
  if (V("lv_selector") === v) return;
  setValue(S.byKey.lv_selector, v);
}));
$("#modeChip").addEventListener("click", () => openValuePicker($("#modeChip"), S.byKey.mode));
$("#formatChip").addEventListener("click", () => openValuePicker($("#formatChip"), S.byKey.frame_size));
$("#formatChip").style.cursor = "pointer";

$("#recBtn").addEventListener("click", toggleRecord);
async function toggleRecord() {
  const on = !S.status.recording;
  try { await send("record", on); }
  catch (e) { toast(e.message, "error"); }
}

$("#lvTimerChip").addEventListener("click", async () => {
  if (!confirm("Restart live view to reset the camera's auto-off timer? The picture (and HDMI output) blanks for 1–2 seconds — don't do it mid-take.")) return;
  try { await send("restart_lv"); toast("Live view restarted — timer reset", "ok"); } catch (e) { toast(e.message, "error"); }
});

$("#fullBtn").addEventListener("click", toggleFullscreen);
function toggleFullscreen() {
  if (document.fullscreenElement) document.exitFullscreen();
  else document.documentElement.requestFullscreen().catch(() => {});
}
document.addEventListener("fullscreenchange", () => { document.body.classList.toggle("fs", !!document.fullscreenElement); });

$("#helpBtn").addEventListener("click", () => ($("#helpModal").hidden = false));
$("#guideBtn").addEventListener("click", () => ($("#guideModal").hidden = false));
$("#guideModal").addEventListener("click", (e) => { if (e.target.id === "guideModal" || e.target.closest("[data-close]")) $("#guideModal").hidden = true; });
$("#helpModal").addEventListener("click", (e) => { if (e.target.id === "helpModal" || e.target.closest("[data-close]")) $("#helpModal").hidden = true; });

/* ======================================================================
   Keyboard
   ====================================================================== */
document.addEventListener("keydown", (e) => {
  const t = e.target;
  if (t && (t.tagName === "INPUT" || t.tagName === "SELECT" || t.tagName === "TEXTAREA")) return;
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  const visible = DIALS.filter((d) => !d.when || d.when());
  switch (e.key) {
    case "r": case "R": toggleRecord(); break;
    case "f": doAutofocus(); break;
    case "[": manualFocus(-MF_STEPS.fine); break;
    case "]": manualFocus(MF_STEPS.fine); break;
    case "{": manualFocus(-MF_STEPS.big); break;
    case "}": manualFocus(MF_STEPS.big); break;
    case "z": case "Z": cycleZoom(); break;
    case "g": toggleOverlay("grid"); break;
    case "s": toggleOverlay("safe"); break;
    case "e": toggleOverlay("zebra"); break;
    case "p": toggleOverlay("peaking"); break;
    case "h": toggleOverlay("hist"); break;
    case "l": toggleOverlay("level"); break;
    case "a": toggleOverlay("face"); break;
    case "?": $("#helpModal").hidden = !$("#helpModal").hidden; break;
    case "Escape": $("#helpModal").hidden = true; $("#guideModal").hidden = true; closePop(); break;
    case "ArrowLeft": case "ArrowRight":
      if (visible[S.selectedDial]) { e.preventDefault(); stepDial(visible[S.selectedDial], e.key === "ArrowLeft" ? -1 : 1); }
      break;
    default:
      if (/^[1-6]$/.test(e.key) && visible[Number(e.key) - 1]) { S.selectedDial = Number(e.key) - 1; renderDials(); }
      else return;
  }
});

/* ======================================================================
   Face check
   ====================================================================== */
function faceItems() {
  const f = S.face, out = [];
  const add = (level, title, detail) => out.push({ level, title, detail });
  if (!S.status.lv) return out;
  if (!f || !f.found) { add("warn", "No face in view", "Sit where you'll record; the checks start when your face is visible."); return out; }
  const t = f.target ?? (S.assist && S.assist.face_target) ?? 58;
  const d = f.face_luma - t;
  if (Math.abs(d) <= 4) add("ok", `Face exposure ${f.face_luma}%`, `Target ${t}%.`);
  else add("warn", `Face ${d < 0 ? "too dark" : "too bright"}: ${f.face_luma}%`, `Target ${t}%. Press “Expose for my face”.`);
  if (f.face_clip > 0.02) add("warn", "Highlights on your face are clipping", `${Math.round(f.face_clip * 100)}% of your face is pure white — lower ISO or soften/dim the light.`);
  if (f.focus_ratio == null) add("warn", "Focus not confirmed", "Press “Focus on my eyes” (or click your eye in the preview).");
  else if (f.focus_ratio < 0.6) add("warn", "Eyes look softer than after the last focus", "Press “Focus on my eyes” again.");
  else add("ok", "Eyes in focus");
  if (f.framing && f.framing.length) f.framing.forEach((tip) => add("warn", "Framing", tip));
  else add("ok", "Good framing", "Eyes on the upper third, centred.");
  if (f.separation_stops != null) {
    if (f.separation_stops >= 2) add("ok", `Background ${f.separation_stops.toFixed(1)} stops darker than you`);
    else add("warn", `Background only ${Math.max(0, f.separation_stops).toFixed(1)} stops darker than you`, "For a dark background: turn off lights behind you, light only your face, keep Active D-Lighting off.");
  }
  return out;
}

function renderFace() {
  const items = faceItems();
  const list = $("#faceList");
  list.innerHTML = "";
  for (const c of items) {
    list.append(el("li", { class: c.level }, icon(c.level === "ok" ? "i-check" : c.level === "bad" ? "i-x" : "i-warn"),
      el("div", { class: "check-text" }, el("div", { class: "check-title", text: c.title }), c.detail ? el("div", { class: "check-detail", text: c.detail }) : null)));
  }
  if (!S.status.lv) list.append(el("li", { class: "preset-empty", text: "Starts when live view is running." }));
  const warn = items.filter((i) => i.level !== "ok").length;
  const sum = $("#faceSummary");
  sum.textContent = !items.length ? "" : warn ? `${warn} to fix` : "Looking good";
  sum.className = "checks-summary " + (warn ? "warn" : "ok");
  const found = S.face && S.face.found;
  $("#faceExposeBtn").disabled = !found; $("#faceFocusBtn").disabled = !found; $("#faceRememberBtn").disabled = !found;
  drawOverlay();
}

async function faceAction(btn, op, okText) {
  btn.disabled = true;
  const label = btn.textContent;
  btn.textContent = "Working…";
  try {
    const r = await send(op);
    if (op === "face_expose") {
      if (r.ok) toast(`Face exposed: ${r.face}% at ISO ${r.iso} (target ${r.target}%)`, "ok");
      else toast(r.message || "Couldn't reach the target", "error");
    } else if (op === "face_focus") {
      r.focused ? toast("Focused on your eyes", "ok") : toast("Couldn't lock focus on your eyes — more light on your face helps", "error");
    } else if (op === "face_remember") {
      if (S.assist) S.assist.face_target = r.target;
      toast(okText.replace("{t}", r.target), "ok");
    }
  } catch (e) { toast(e.message, "error"); }
  btn.textContent = label;
  btn.disabled = false;
}
$("#faceExposeBtn").addEventListener("click", (e) => faceAction(e.currentTarget, "face_expose"));
$("#faceFocusBtn").addEventListener("click", (e) => faceAction(e.currentTarget, "face_focus"));
$("#faceRememberBtn").addEventListener("click", (e) => faceAction(e.currentTarget, "face_remember", "Saved {t}% as your face target"));

/* ======================================================================
   Voice & mic
   ====================================================================== */
const dbPct = (v, lo = -60) => Math.max(0, Math.min(100, ((v - lo) / -lo) * 100));
function renderAudioLevels() {
  const a = S.audio || {};
  const peak = a.peak ?? -120, rms = a.rms ?? -120;
  $("#amRms").style.width = dbPct(rms) + "%";
  $("#amPeak").style.left = `calc(${dbPct(peak)}% - 1px)`;
  const stats = $("#amStats");
  if (a.error) stats.innerHTML = `<span class="bad">${escapeHtml(a.error)}</span>`;
  else stats.innerHTML = `Peak <b>${fmtDb(a.peak)}</b> · Loudness <b>${a.lufs_s != null && a.lufs_s > -70 ? a.lufs_s.toFixed(0) + " LUFS" : "–"}</b> · Floor <b>${fmtDb(a.floor)}</b>` +
    (a.clipping ? ` · <span class="bad">CLIPPING — GAIN down</span>` : "") +
    (a.checking ? ` · <b>Keep talking… ${Math.ceil(a.check_left)} s</b>` : "");
  const meter = $("#micMeter");
  meter.style.setProperty("--lvl", dbPct(rms) + "%");
  meter.style.setProperty("--pk", dbPct(peak) + "%");
  meter.classList.toggle("clip", !!a.clipping);
  $("#micLufs").textContent = a.lufs_s != null && a.lufs_s > -70 ? `${a.lufs_s.toFixed(0)}` : "–";
  $("#micFoot").textContent = a.error ? "no input" : a.clipping ? "CLIP" : a.checking ? `check ${Math.ceil(a.check_left)}s` : a.speaking ? `pk ${fmtDb(peak)}` : "LUFS";
  const sum = $("#audioSummary");
  sum.textContent = a.error ? "No input" : a.clipping ? "Clipping" : a.speaking ? "Voice" : "Listening";
  sum.className = "checks-summary " + (a.error || a.clipping ? "warn" : "ok");
}
function fmtDb(v) { return v == null || v < -100 ? "–" : `${v.toFixed(0)} dB`; }

async function loadAudioSources() {
  try {
    const r = await send("audio_sources");
    const sel = $("#audioSource");
    sel.innerHTML = "";
    for (const src of r.sources) sel.append(el("option", { value: src.name, text: src.description }));
    if (r.current) sel.value = r.current;
  } catch { /* audio monitor not available */ }
}
$("#audioSource").addEventListener("change", (e) => run("audio_select", e.target.value).then(() => toast("Listening to " + e.target.selectedOptions[0].text, "ok")).catch(() => {}));

$("#voiceCheckBtn").addEventListener("click", async (e) => {
  const btn = e.currentTarget;
  btn.disabled = true;
  toast("Talk now, as you would on camera, for 15 seconds…", "info");
  try {
    S.voiceReport = await send("voice_check", 15);
    S.voiceReport.at = new Date();
    renderVoiceReport();
  } catch (err) { toast(err.message, "error"); }
  btn.disabled = false;
});

function renderVoiceReport() {
  const r = S.voiceReport, box = $("#voiceReport");
  box.innerHTML = "";
  if (!r) return;
  const head = r.loudness != null
    ? `Voice check ${r.at.toLocaleTimeString()}: peaks ${r.peak_p95} dBFS · loudness ${r.loudness} LUFS · range ${r.lra ?? "–"} LU`
    : `Voice check ${r.at.toLocaleTimeString()}`;
  box.append(el("div", { class: "vr-head", text: head }));
  const list = el("ul", { class: "check-list" });
  for (const rec of r.recommendations) {
    const title = el("div", { class: "check-title" }, el("span", { class: `knob ${rec.action}`, text: rec.control }), rec.text);
    if (rec.amount) title.append(el("span", { class: "amount", text: rec.amount }));
    list.append(el("li", { class: rec.level }, icon(rec.level === "ok" ? "i-check" : rec.level === "bad" ? "i-x" : "i-warn"), el("div", { class: "check-text" }, title)));
  }
  box.append(list);
  const todo = r.recommendations.filter((x) => x.level !== "ok").length;
  box.append(el("div", { class: "vr-head", text: todo ? "Adjust, then run the check again." : "Sounds good — ready to record." }));
}

function expandCard(id) {
  const c = $("#" + id);
  c.classList.remove("collapsed"); S.ui.collapsed[id] = false; savePrefs();
  c.scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ======================================================================
   Collapsible cards
   ====================================================================== */
$$(".collapsible").forEach((card) => {
  if (S.ui.collapsed[card.id]) card.classList.add("collapsed");
  $("[data-toggle]", card).addEventListener("click", () => {
    card.classList.toggle("collapsed");
    S.ui.collapsed[card.id] = card.classList.contains("collapsed");
    savePrefs();
  });
});

/* ======================================================================
   Presets
   ====================================================================== */
let presets = {};
async function loadPresets() {
  try { presets = await send("presets"); } catch { presets = {}; }
  renderPresets();
}
function renderPresets() {
  const list = $("#presetList");
  list.innerHTML = "";
  const names = Object.keys(presets);
  const builtin = names.filter((n) => presets[n].builtin);
  const mine = names.filter((n) => !presets[n].builtin).sort((a, b) => a.localeCompare(b));
  const row = (name) => {
    const pr = presets[name];
    const active = S.ui.activePreset === name;
    const apply = el("button", { class: "btn btn-sm" + (active ? " on" : ""), text: active ? "Re-apply" : "Apply", title: "Apply every setting in this preset to the camera" });
    apply.addEventListener("click", () => applyPreset(name, apply));
    const meta = pr.builtin ? pr.description : `${pr.movie ? "Movie" : "Photo"} · ${Object.keys(pr.values).length} settings`;
    const li = el("li", { class: active ? "active" : "" },
      el("div", { class: "preset-name" }, el("div", { text: name }), el("div", { class: "preset-meta", text: meta })), apply);
    if (!pr.builtin) {
      const del = el("button", { class: "icon-btn", title: `Delete "${name}"` }, icon("i-trash"));
      del.addEventListener("click", async () => {
        if (!confirm(`Delete the preset "${name}"?`)) return;
        await run("delete_preset", name).catch(() => {});
        if (S.ui.activePreset === name) { S.ui.activePreset = null; savePrefs(); }
        loadPresets();
      });
      li.append(del);
    }
    return li;
  };
  if (builtin.length) list.append(el("li", { class: "preset-group", text: "Recommended — talking head, dark background" }));
  builtin.forEach((n) => list.append(row(n)));
  list.append(el("li", { class: "preset-group", text: "Your presets" }));
  if (!mine.length) list.append(el("li", { class: "preset-empty", text: "Tune the camera, then “Save current…” to keep your own setups." }));
  mine.forEach((n) => list.append(row(n)));
  renderAll(false);
}

async function applyPreset(name, btn) {
  if (btn) btn.disabled = true;
  try {
    const r = await send("apply_preset", name);
    S.ui.activePreset = name; savePrefs();
    if (r.failed && r.failed.length) toast(`Applied "${name}" except: ${r.failed.join("; ")}`, "error");
    else toast(`Applied "${name}". Now click your eye in the preview to focus, then set ISO so your face looks right.`, "ok");
  } catch (e) { toast(e.message, "error"); }
  if (btn) btn.disabled = false;
  renderPresets();
}

// Settings a preset leaves to you: ISO is tuned to the light on the day.
const PRESET_FREE = new Set(["movie_iso", "iso", "lv_selector"]);
function presetDiff(name) {
  const pr = presets[name];
  if (!pr) return null;
  const diffs = [];
  for (const [code, want] of Object.entries(pr.values)) {
    const s = S.byCode[code], p = S.props[code];
    if (!s || !p || PRESET_FREE.has(s.key)) continue;
    let target = want;
    if (p.form === "enum" && p.vals && !p.vals.includes(want) && typeof want === "number") target = p.vals.reduce((a, b) => (Math.abs(b - want) < Math.abs(a - want) ? b : a));
    if (p.v !== target) diffs.push(`${s.label}: ${fmtValue(s, p.v)} → ${fmtValue(s, target)}`);
  }
  return diffs;
}

$("#savePresetBtn").addEventListener("click", () => { $("#presetForm").hidden = false; $("#presetName").focus(); });
$("#presetCancel").addEventListener("click", () => { $("#presetForm").hidden = true; });
$("#presetForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = $("#presetName").value.trim();
  if (!name) return;
  if (presets[name] && !confirm(`Replace the existing preset "${name}"?`)) return;
  try {
    const r = await send("save_preset", name);
    toast(`Saved "${r.name}" (${r.count} settings)`, "ok");
    S.ui.activePreset = r.name; savePrefs();
    $("#presetName").value = ""; $("#presetForm").hidden = true;
    loadPresets();
  } catch (err) { toast(err.message, "error"); }
});

/* ======================================================================
   Save frame
   ====================================================================== */
$("#snapBtn").addEventListener("click", () => {
  if (!lastBitmap) { toast("No preview frame yet", "error"); return; }
  const c = document.createElement("canvas");
  c.width = lastBitmap.width; c.height = lastBitmap.height;
  c.getContext("2d").drawImage(lastBitmap, 0, 0);
  const n = new Date(), pad = (x) => String(x).padStart(2, "0");
  const ts = `${n.getFullYear()}-${pad(n.getMonth() + 1)}-${pad(n.getDate())}_${pad(n.getHours())}-${pad(n.getMinutes())}-${pad(n.getSeconds())}`;
  c.toBlob((b) => {
    const a = el("a", { href: URL.createObjectURL(b), download: `nikon-preview-${ts}.png` });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }, "image/png");
});

/* ======================================================================
   Toasts
   ====================================================================== */
function toast(text, level = "info") {
  const box = $("#toasts");
  const t = el("div", { class: `toast ${level}`, text });
  box.append(t);
  while (box.childElementCount > 4) box.firstChild.remove();
  setTimeout(() => t.remove(), level === "error" ? 6000 : 3200);
}
function escapeHtml(s) { return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

/* ======================================================================
   Render all
   ====================================================================== */
let renderQueued = false, tabsDirty = true;
function renderAll(tabs = true) {
  if (tabs) tabsDirty = true;
  if (renderQueued) return;
  renderQueued = true;
  requestAnimationFrame(() => {
    renderQueued = false;
    if (!S.catalog) return;
    renderTopbar();
    renderDials();
    renderFocusControls();
    renderOverlayToggles();
    renderChecks();
    renderFace();
    if (tabsDirty) { tabsDirty = false; renderTabs(); }
    renderViewerState();
  });
}

setInterval(() => { if (S.catalog) renderViewerState(); }, 1000);
setTimeout(() => $("#clickHint").classList.add("fade"), 12000);
renderOverlayToggles();
connect();
