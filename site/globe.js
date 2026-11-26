// The Lineup globe: every in-person meetup in your current view, glowing on a spinning globe.
// Drag to spin. Tap a city chip to fly there and filter the list. Follows every filter on the page.
import createGlobe from "https://cdn.jsdelivr.net/npm/cobe@0.6.3/+esm";

const hero = document.getElementById("hero");
const canvas = document.getElementById("globe");
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

function webglOK() {
  try { const c = document.createElement("canvas"); return !!(c.getContext("webgl2") || c.getContext("webgl")); } catch (_) { return false; }
}

if (hero && canvas && webglOK()) {
  hero.hidden = false;
  // phones: the filters stack first, so lift the globe to the very top of the page
  const mq = matchMedia("(max-width: 900px)"), board = hero.parentElement, app = document.querySelector(".app");
  const place = () => { if (mq.matches && app) app.insertBefore(hero, app.firstChild); else if (board) board.insertBefore(hero, board.firstChild); };
  place(); mq.addEventListener("change", place);
  const TAU = Math.PI * 2;
  let markers = [], cities = [], hovered = -1, nextKey = "", R_K = 0.8, phi = -1.35, theta = 0.32, targetPhi = null, targetTheta = null;
  let dragging = false, lastX = 0, lastY = 0, velocity = 0, width = 0, idleSince = 0;
  const toAngles = (lat, lng) => [Math.PI - ((lng * Math.PI) / 180 - Math.PI / 2), (lat * Math.PI) / 180];

  const size = () => {
    width = canvas.offsetWidth || canvas.parentElement.offsetWidth || 360;
  };
  size(); addEventListener("resize", size);
  await new Promise((r) => requestAnimationFrame(r)); size();  // measure after the hero is laid out

  const globe = createGlobe(canvas, {
    devicePixelRatio: Math.min(2, Math.max(1, window.devicePixelRatio || 1)),
    width: width * 2, height: width * 2,
    phi, theta, dark: 1, diffuse: 1.25, mapSamples: 16000, mapBrightness: 5.5,
    baseColor: [0.22, 0.25, 0.29], markerColor: [1, 0.71, 0.28], glowColor: [0.16, 0.18, 0.22],
    markers: [], opacity: 0.92,
    onRender: (s) => {
      if (targetPhi !== null) {
        let d = ((targetPhi - phi) % TAU + TAU * 1.5) % TAU - TAU / 2;  // shortest way round
        phi += d * 0.08; theta += (targetTheta - theta) * 0.08;
        if (Math.abs(d) < 0.002 && Math.abs(targetTheta - theta) < 0.002) targetPhi = null;
      } else if (!dragging) {
        phi += velocity; velocity *= 0.95;
        if (!reduce && Date.now() - idleSince > 2500) phi += 0.0022;  // gentle spin when nobody's touching it
      }
      s.phi = phi; s.theta = theta; s.width = canvas.width; s.height = canvas.height;  // always match the real drawing buffer
      const t = performance.now() / 1000;
      s.markers = cities.map((c, i) => ({ location: [c.lat, c.lng],
        size: c.size * (i === hovered ? 1.9 : c.key === nextKey ? 1 + 0.35 * (0.5 + 0.5 * Math.sin(t * 3)) : 1) }));
    },
  });
  requestAnimationFrame(() => canvas.classList.add("on"));

  // drag to spin (mouse and touch)
  canvas.addEventListener("pointerdown", (e) => { dragging = true; targetPhi = null; lastX = e.clientX; lastY = e.clientY; canvas.setPointerCapture(e.pointerId); });
  canvas.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    const dx = e.clientX - lastX, dy = e.clientY - lastY; lastX = e.clientX; lastY = e.clientY;
    velocity = dx / 220; phi += velocity; theta = Math.max(-0.6, Math.min(0.9, theta + dy / 300));
  });
  const end = () => { dragging = false; idleSince = Date.now(); };
  canvas.addEventListener("pointerup", end); canvas.addEventListener("pointercancel", end);

  const $ = (s) => hero.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  let first = true, nextTimer = 0;

  function countUp(el, to) {
    const from = +el.dataset.n || 0; el.dataset.n = to;
    if (reduce || from === to) { el.textContent = to; return; }
    const t0 = performance.now(), dur = first ? 1100 : 500;
    const step = (t) => { const k = Math.min(1, (t - t0) / dur), v = Math.round(from + (to - from) * (1 - Math.pow(1 - k, 3))); el.textContent = v; if (k < 1) requestAnimationFrame(step); };
    requestAnimationFrame(step);
  }
  function fmtIn(ms) {
    if (ms <= 0) return "happening now";
    const m = Math.floor(ms / 60000), d = Math.floor(m / 1440), h = Math.floor((m % 1440) / 60);
    return d ? `in ${d}d ${h}h` : h ? `in ${h}h ${m % 60}m` : `in ${m}m`;
  }

  function pickCity(c) {
    [targetPhi, targetTheta] = toAngles(c.lat, c.lng); targetTheta = Math.max(-0.6, Math.min(0.9, targetTheta * 0.85));
    dispatchEvent(new CustomEvent("lineup:pick", { detail: { country: c.country,
      region: c.country === "United States" && c.states.size === 1 ? c.state : "",
      metro: Object.entries(c.metros).sort((a, b) => b[1] - a[1])[0][0] } }));
  }
  // where a lat/lng lands on screen right now (same rotation cobe uses), or null if it's round the back
  function project(lat, lng) {
    const la = (lat * Math.PI) / 180, lo = (lng * Math.PI) / 180 - Math.PI;
    let x = -Math.cos(la) * Math.cos(lo), y = Math.sin(la), z = Math.cos(la) * Math.sin(lo);
    const cp = Math.cos(phi), sp = Math.sin(phi), ct = Math.cos(theta), st = Math.sin(theta);
    [x, z] = [cp * x + sp * z, -sp * x + cp * z];
    [y, z] = [ct * y - st * z, st * y + ct * z];
    if (z < 0.12) return null;
    const w = canvas.offsetWidth, r = (w / 2) * R_K;
    return { x: w / 2 + x * r, y: w / 2 - y * r };
  }
  const tip = document.createElement("div");
  tip.className = "g-tip"; tip.hidden = true;
  canvas.parentElement.appendChild(tip);
  function hideTip() { tip.hidden = true; }
  function nearest(px, py) {
    let best = -1, bd = 22 * 22;
    cities.forEach((c, i) => { const p = project(c.lat, c.lng); if (!p) return;
      const d = (p.x - px) ** 2 + (p.y - py) ** 2; if (d < bd) { bd = d; best = i; } });
    return best;
  }
  let tipFor = -1;
  function showTip(i) {
    const c = cities[i], p = c && project(c.lat, c.lng);
    if (!p) { hideTip(); return; }
    if (tipFor !== i || tip.hidden) {
      const nx = c.events.find((e) => new Date(e.end || e.start) > new Date());
      const when = nx ? new Date(nx.start).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" }) : "";
      tip.innerHTML = `<b>${esc(c.name)}</b><span>${c.n} meetup${c.n === 1 ? "" : "s"}</span>`
        + (nx ? `<em>Next: ${esc(nx.title.length > 52 ? nx.title.slice(0, 50) + "…" : nx.title)} · ${esc(when)}</em>` : "")
        + `<button type="button">See ${c.n === 1 ? "it" : "all " + c.n} →</button>`;
      tip.querySelector("button").onclick = (e) => { e.stopPropagation(); pickCity(c); hovered = -1; hideTip(); };
      tipFor = i;
    }
    tip.hidden = false;
    const w = canvas.offsetWidth;
    tip.style.left = Math.min(Math.max(p.x, 100), w - 100) + "px"; tip.style.top = p.y + "px";
    tip.classList.toggle("g-tip--below", p.y < 130);
  }
  let downAt = null;
  canvas.addEventListener("pointerdown", (e) => { downAt = { x: e.clientX, y: e.clientY }; });
  canvas.addEventListener("pointermove", (e) => {
    if (dragging || e.pointerType === "touch") return;
    const r = canvas.getBoundingClientRect(), i = nearest(e.clientX - r.left, e.clientY - r.top);
    canvas.style.cursor = i >= 0 ? "pointer" : "grab";
    if (i !== hovered) { hovered = i; i >= 0 ? showTip(i) : hideTip(); }
    if (i >= 0) idleSince = Date.now() + 4000;  // hold still while you read
  });
  canvas.addEventListener("pointerleave", (e) => {
    if (e.pointerType === "touch") return;
    setTimeout(() => { if (!tip.matches(":hover")) { hovered = -1; hideTip(); } }, 300);
  });
  tip.addEventListener("pointerleave", () => { hovered = -1; hideTip(); });
  canvas.addEventListener("pointerup", (e) => {
    if (!downAt || Math.hypot(e.clientX - downAt.x, e.clientY - downAt.y) > 6) return;  // that was a drag
    const r = canvas.getBoundingClientRect(), i = nearest(e.clientX - r.left, e.clientY - r.top);
    if (i < 0) { hovered = -1; hideTip(); return; }
    if (e.pointerType === "touch" && hovered !== i) { hovered = i; showTip(i); idleSince = Date.now() + 6000; return; }  // first tap: peek
    pickCity(cities[i]); hovered = -1; hideTip();
  });
  window.__lineupGlobe = { project, cities: () => cities, setR: (k) => { R_K = k; }, freeze: () => { idleSince = Date.now() + 1e9; velocity = 0; } };
  // keep the tooltip glued to its dot while the globe turns
  (function follow() { if (!tip.hidden && hovered >= 0) showTip(hovered); requestAnimationFrame(follow); })();

  // the page tells us whenever the filters change
  addEventListener("lineup:update", (ev) => {
    const { events, placeLabel, focus } = ev.detail;
    const live = events.filter((e) => !e.online && e.lat != null && e.status !== "cancelled");
    const byCity = new Map();
    for (const e of live) {
      const nm = (e.metro || e.city).replace(/ area$/i, ""), k = nm + "|" + e.country;
      const c = byCity.get(k) || { name: nm, metro: e.metro || e.city, state: e.state, states: new Set(), metros: {}, country: e.country, lat: e.lat, lng: e.lng, n: 0 };
      c.n++; c.states.add(e.state); const mm = e.metro || e.city; c.metros[mm] = (c.metros[mm] || 0) + 1; byCity.set(k, c);
    }
    cities = [...byCity.values()].sort((a, b) => b.n - a.n);
    for (const c of cities) c.events = live.filter((e) => ((e.metro || e.city).replace(/ area$/i, "") + "|" + e.country) === c.name + "|" + c.country)
      .sort((a, b) => new Date(a.start) - new Date(b.start));
    cities.forEach((c) => { c.size = Math.min(0.11, 0.035 + Math.sqrt(c.n) * 0.016); c.key = c.name + "|" + c.country; });
    hovered = -1; hideTip();

    countUp($("#g-events"), events.filter((e) => e.status !== "cancelled").length);
    countUp($("#g-cities"), cities.length);
    $("#g-where").textContent = placeLabel;

    $("#g-chips").innerHTML = cities.slice(0, 8).map((c, i) =>
      `<button type="button" class="g-chip" data-i="${i}">${esc(c.name)}<span>${c.n}</span></button>`).join("")
      + (ev.detail.narrowed ? `<button type="button" class="g-chip g-chip--all" data-all="1">← All cities</button>` : "");
    $("#g-chips").onclick = (e) => {
      const b = e.target.closest(".g-chip"); if (!b) return;
      if (b.dataset.all) { dispatchEvent(new CustomEvent("lineup:pick", { detail: { country: ev.detail.country, region: "", metro: "" } })); return; }
      pickCity(cities[+b.dataset.i]);
    };

    // fly to whatever the filters point at (a state, a city, or near me)
    if (focus && cities.length) {
      const lat = cities.reduce((s, c) => s + c.lat * c.n, 0) / cities.reduce((s, c) => s + c.n, 0);
      const lng = cities.reduce((s, c) => s + c.lng * c.n, 0) / cities.reduce((s, c) => s + c.n, 0);
      [targetPhi, targetTheta] = toAngles(lat, lng); targetTheta = Math.max(-0.6, Math.min(0.9, targetTheta * 0.85));
    } else if (first) {
      [targetPhi, targetTheta] = toAngles(39, -82); targetTheta = 0.42;  // open on the US east coast
    }

    // live countdown to the next in-person event in view
    clearInterval(nextTimer);
    const next = live.filter((e) => new Date(e.end || e.start) > new Date()).sort((a, b) => new Date(a.start) - new Date(b.start))[0];
    nextKey = next ? (next.metro || next.city).replace(/ area$/i, "") + "|" + next.country : "";
    const tick = () => {
      if (!next) { $("#g-next").textContent = "No in-person events in this view yet."; return; }
      $("#g-next").innerHTML = `<i></i>Next up ${esc(fmtIn(new Date(next.start) - new Date()))}: <a href="${esc(next.page || "#")}">${esc(next.title)}</a> · ${esc(next.metro || next.city)}`;
    };
    tick(); nextTimer = setInterval(tick, 30000);
    first = false;
  });

  // if the page loaded its events before this module, ask it to resend
  dispatchEvent(new CustomEvent("lineup:globe-ready"));
  addEventListener("pagehide", () => globe.destroy());
}
